"""The object store's certificate is a dated dependency, so something watches it.

Exports, models and manual uploads all go through the store now. Two ways it
breaks: the certificate expires, or it is renewed under a chain our CA bundle
does not carry — botocore ships its own vendored bundle which lacks the
`HARICA TLS RSA Root CA 2021` this endpoint uses, so we only work because the
client is pointed at certifi. The second case is the one a plain "days remaining"
check would miss, which is why the handshake goes through the same bundle.

Issue 033 is the precedent: an expired certificate on someone else's service
crash-looped both twins for 21 restarts.
"""

from datetime import UTC, datetime, timedelta

import pytest

from wp6_data.config import ObjectStoreSettings
from wp6_data.shared.object_store_health import (
    CRITICAL_DAYS,
    WARN_DAYS,
    StoreHealth,
    check,
    render_status_card,
)


def _health(**kw) -> StoreHealth:
    base = {"configured": True, "endpoint": "https://store.example:4477", "bucket": "b"}
    return StoreHealth(**{**base, **kw})


class TestState:
    def test_plenty_of_time_is_ok(self):
        assert _health(cert_days=WARN_DAYS + 1).state == "ok"

    def test_just_inside_the_window_warns(self):
        assert _health(cert_days=WARN_DAYS - 1).state == "warn"

    def test_close_to_expiry_is_critical(self):
        assert _health(cert_days=CRITICAL_DAYS - 1).state == "critical"

    def test_already_expired_is_critical(self):
        assert _health(cert_days=-3).state == "critical"

    def test_a_failed_handshake_is_critical_however_many_days_remain(self):
        """The renewal-under-an-untrusted-chain case. Days remaining are
        irrelevant if we cannot complete the handshake at all."""
        assert _health(cert_days=300, error="SSLCertVerificationError").state == "critical"

    def test_unconfigured_is_off_not_broken(self):
        assert StoreHealth(configured=False).state == "off"

    def test_plain_http_has_nothing_to_expire(self):
        """The local container is http; absence of a cert is not a problem."""
        assert _health(endpoint="http://localhost:9100", cert_days=None).state == "ok"


class TestCheck:
    @pytest.mark.asyncio
    async def test_unconfigured_store_reports_off_without_touching_the_network(self):
        health = await check(ObjectStoreSettings(bucket=""))

        assert health.configured is False
        assert health.state == "off"

    @pytest.mark.asyncio
    async def test_http_endpoint_skips_the_handshake(self):
        health = await check(
            ObjectStoreSettings(bucket="b", endpoint_url="http://localhost:9100"),
        )

        assert health.configured is True
        assert health.cert_days is None
        assert health.error == ""
        assert health.state == "ok"

    @pytest.mark.asyncio
    async def test_an_unreachable_host_is_reported_not_raised(self):
        """This runs while rendering a status page; an exception here would 500
        the page whose job is to say whether things are healthy."""
        health = await check(
            ObjectStoreSettings(bucket="b", endpoint_url="https://127.0.0.1:9"),
        )

        assert health.error
        assert health.state == "critical"


class TestCard:
    def test_unconfigured_card_says_what_needs_it(self):
        html = render_status_card(StoreHealth(configured=False))

        assert "Not configured" in html
        assert "manual uploads" in html

    def test_a_healthy_card_does_not_nag(self):
        html = render_status_card(
            _health(cert_days=200, cert_issuer="X",
                    cert_expires=datetime.now(UTC) + timedelta(days=200)),
        )

        assert "OK" in html
        assert "probe harness" not in html

    def test_a_warning_card_names_the_issuer_and_says_what_to_do(self):
        """The issuer is the signal that a renewal changed the chain — a day
        count alone would not show it."""
        html = render_status_card(
            _health(cert_days=11, cert_issuer="GEANT TLS RSA 1",
                    cert_expires=datetime(2026, 10, 11, tzinfo=UTC)),
        )

        assert "RENEW SOON" in html
        assert "GEANT TLS RSA 1" in html
        assert "2026-10-11" in html
        assert "probe harness" in html

    def test_a_failed_handshake_card_explains_it_used_the_client_s_bundle(self):
        html = render_status_card(_health(error="SSLCertVerificationError: bad chain"))

        assert "ACTION NEEDED" in html
        assert "SSLCertVerificationError" in html
        assert "same CA bundle" in html
