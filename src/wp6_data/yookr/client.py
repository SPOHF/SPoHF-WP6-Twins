"""Yookr API client — login + sensor reading queries.

Auth uses a cookie (``yookr-authentication-live``) set by the ``/login``
endpoint.  An ``httpx.Client`` with a cookie jar handles this automatically.
"""

from datetime import datetime

import httpx
import structlog

logger = structlog.get_logger()


class YookrClient:
    """Synchronous client for the Yookr sensor API.

    Authenticates via /login (email + password).  The server sets an
    HttpOnly cookie (``yookr-authentication-live``) which httpx sends
    on subsequent requests automatically.
    """

    def __init__(self, base_url: str, email: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Return a logged-in httpx client (lazy, re-creates on 401)."""
        if self._client is None:
            self._client = httpx.Client(timeout=30.0)
            self._login()
        return self._client

    def _login(self) -> None:
        """Authenticate — the response sets the auth cookie on the client."""
        client = self._client or httpx.Client(timeout=30.0)
        resp = client.post(
            f"{self._base_url}/login",
            json={"email": self._email, "password": self._password},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            msg = f"Login failed: {data.get('message', 'unknown error')}"
            raise RuntimeError(msg)
        self._client = client
        logger.info("yookr_login_ok")

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def fetch_readings(
        self,
        sensor_id: str,
        *,
        gte: datetime | None = None,
        lte: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        """Fetch measurements for a single sensor.

        Returns list of dicts with keys: sensorId, datetimeMeasure, value, metadata.
        """
        client = self._get_client()

        params: dict[str, str | int] = {"limit": limit}
        if gte:
            params["gte"] = gte.isoformat()
        if lte:
            params["lte"] = lte.isoformat()
        params["order"] = "datetimeMeasure DESC"

        url = f"{self._base_url}/sensor/{sensor_id}/read"
        resp = client.get(url, params=params)

        # Re-authenticate once on 401 (cookie expired)
        if resp.status_code == 401:
            logger.info("yookr_cookie_expired, re-authenticating")
            self._login()
            resp = client.get(url, params=params)

        resp.raise_for_status()
        data = resp.json()

        if len(data) >= limit:
            logger.warning(
                "yookr_limit_reached",
                sensor_id=sensor_id,
                limit=limit,
                returned=len(data),
                hint="results may be truncated — consider a smaller time range",
            )

        return data
