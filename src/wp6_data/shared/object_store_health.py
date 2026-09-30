"""Is the object store reachable, and is its certificate about to become a problem?

Exports, trained models and manual uploads all live in the object store now, so an
outage there is not cosmetic — and one of the two ways it can break is on a
calendar.

**Why the certificate needs watching specifically.** botocore does not use the
system trust store or certifi: it ships its own vendored ``cacert.pem``, which
carries the older Hellenic 2015 roots but *not* the
``HARICA TLS RSA Root CA 2021`` that anchors this endpoint's chain. Everything
works only because the client is pointed at certifi explicitly (see
``ObjectStoreSettings.ca_bundle``). So a renewal under a different issuer is not
automatically fine — it is fine only if the bundle we pass happens to carry the
new root.

This checks the handshake through **the same bundle botocore is given**, so a
chain we would reject shows up here rather than in a 3 a.m. export job. Issue 033
is the precedent: an expired certificate on someone else's service crash-looped
both twins for 21 restarts.

Nothing here knows about red or blue.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from wp6_data.config import ObjectStoreSettings

#: Renew by this point. Chosen to leave room for a chain change to be noticed and
#: the CA bundle updated, not just for the renewal itself.
WARN_DAYS = 21

#: Below this, treat it as an incident rather than a warning.
CRITICAL_DAYS = 7


@dataclass(frozen=True)
class StoreHealth:
    """What a status page needs to say about the object store."""

    configured: bool
    endpoint: str = ""
    bucket: str = ""
    #: None when the endpoint is not https (a local container), or unreachable.
    cert_days: int | None = None
    cert_issuer: str = ""
    cert_expires: datetime | None = None
    #: Populated when the handshake failed. A chain our bundle does not trust
    #: lands here, which is the case a plain "days remaining" would miss.
    error: str = ""

    @property
    def tls(self) -> bool:
        return self.endpoint.startswith("https://")

    @property
    def state(self) -> str:
        """``ok`` | ``warn`` | ``critical`` | ``off``."""
        if not self.configured:
            return "off"
        if self.error:
            return "critical"
        if self.cert_days is None:
            # Plain http, which is the local container. Nothing to expire.
            return "ok"
        if self.cert_days < CRITICAL_DAYS:
            return "critical"
        if self.cert_days < WARN_DAYS:
            return "warn"
        return "ok"

    @property
    def summary(self) -> str:
        if not self.configured:
            return "not configured"
        if self.error:
            return f"certificate check failed: {self.error}"
        if self.cert_days is None:
            return "reachable (no TLS)"
        return f"certificate valid for {self.cert_days} more day(s)"


async def check(settings: ObjectStoreSettings | None = None) -> StoreHealth:
    """Inspect the store's endpoint certificate. Never raises."""
    settings = settings or ObjectStoreSettings()
    if not settings.enabled:
        return StoreHealth(configured=False)

    endpoint = settings.endpoint_url
    base = StoreHealth(configured=True, endpoint=endpoint, bucket=settings.bucket)
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        return base

    host = parsed.hostname
    port = parsed.port or 443
    bundle = settings.ca_bundle or _certifi_path()

    def _handshake() -> StoreHealth:
        try:
            context = ssl.create_default_context(cafile=bundle)
            with (
                socket.create_connection((host, port), timeout=10) as raw,
                context.wrap_socket(raw, server_hostname=host) as tls,
            ):
                cert = tls.getpeercert()
        except Exception as exc:  # noqa: BLE001 - a health check reports, never raises
            return StoreHealth(
                configured=True, endpoint=endpoint, bucket=settings.bucket,
                error=f"{type(exc).__name__}: {exc}",
            )

        expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=UTC,
        )
        issuer = dict(x[0] for x in cert.get("issuer", ()) or ()).get(
            "commonName", "unknown",
        )
        return StoreHealth(
            configured=True, endpoint=endpoint, bucket=settings.bucket,
            cert_days=(expires - datetime.now(UTC)).days,
            cert_issuer=issuer,
            cert_expires=expires,
        )

    return await asyncio.to_thread(_handshake)


def _certifi_path() -> str:
    """The bundle botocore is pointed at when `ca_bundle` is unset.

    Kept in step with ``shared.blob._build_client`` — if these two ever disagree,
    this check stops testing what the client actually does.
    """
    import certifi

    return certifi.where()


def render_status_card(health: StoreHealth) -> str:
    """The object-store card for a twin's status page.

    Deliberately shows the issuer, not just a day count: the failure this guards
    against is a renewal under a chain the CA bundle does not carry, and the
    issuer is what tells you that happened.
    """
    from wp6_data.shared.templates.components import render_card

    if not health.configured:
        return render_card(
            "Object Store",
            "<p>Not configured. Exports, models and manual uploads require it.</p>",
        )

    tone = {
        "ok": ("#16a34a", "OK"),
        "warn": ("#d97706", "RENEW SOON"),
        "critical": ("#dc2626", "ACTION NEEDED"),
    }[health.state]

    rows = [
        ("Bucket", health.bucket),
        ("Endpoint", health.endpoint),
    ]
    if health.cert_expires is not None:
        rows.append(("Certificate expires", health.cert_expires.strftime("%Y-%m-%d")))
        rows.append(("Issuer", health.cert_issuer))
    if health.error:
        rows.append(("Error", health.error))

    detail = "".join(
        f"<tr><td>{label}</td><td><code>{value}</code></td></tr>"
        for label, value in rows
    )
    note = ""
    if health.state in ("warn", "critical") and not health.error:
        note = (
            "<p><small>botocore ships its own CA bundle and does <em>not</em> "
            "carry this chain's root, so the client is pointed at certifi "
            "explicitly. A renewal under a different issuer only works if that "
            "bundle carries the new root — re-run the probe harness "
            "(issue 061) after renewal.</small></p>"
        )
    elif health.error:
        note = (
            "<p><small>The handshake was attempted through the same CA bundle "
            "the S3 client is given, so this is what the client would see. "
            "A chain our bundle does not trust fails here.</small></p>"
        )

    body = (
        f'<p><strong style="color:{tone[0]}">{tone[1]}</strong> — '
        f"{health.summary}</p>"
        f"<table><tbody>{detail}</tbody></table>{note}"
    )
    return render_card("Object Store", body)


async def status_card(_request=None) -> str:
    """A ``TwinConfig.status_extras`` entry. Takes the request the contract
    passes and ignores it."""
    return render_status_card(await check())
