"""SPoHF API client with pagination and retry logic."""

from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from wp6_data.api.models import ApiResponse, SensorReading

logger = structlog.get_logger()


def parse_api_timestamp(ts_str: str) -> datetime:
    """Parse API timestamp string to datetime."""
    # Handle both Z suffix and +00:00
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


class SpoHFClient:
    """Async client for SPoHF sensor data API."""

    def __init__(self, base_url: str, token: str, page_size: int = 1000):
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    )
    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        timestamp_from: datetime,
        timestamp_until: datetime,
        offset: int,
    ) -> ApiResponse:
        """Fetch a single page with retry logic."""
        url = f"{self.base_url}/api/v1/data/{endpoint}"
        params = {
            "timestamp_from": timestamp_from.isoformat(),
            "timestamp_until": timestamp_until.isoformat(),
            "size": str(int(self.page_size)),
            "from": str(int(offset)),
        }

        logger.debug("fetching_page", endpoint=endpoint, offset=offset)

        response = await client.get(
            url,
            params=params,
            headers=self._headers,
            timeout=30.0,
        )
        response.raise_for_status()

        data = response.json()
        return ApiResponse.model_validate(data)

    async def fetch_window(
        self,
        endpoint: str,
        timestamp_from: datetime,
        timestamp_until: datetime,
    ) -> AsyncIterator[SensorReading]:
        """Paginate all records in one time window.

        Args:
            endpoint: API endpoint (e.g., "yookr-data")
            timestamp_from: Start of window (inclusive)
            timestamp_until: End of window (exclusive)

        Yields:
            SensorReading objects
        """
        async with httpx.AsyncClient() as client:
            offset = 0
            page_count = 0
            total_yielded = 0

            while True:
                try:
                    response = await self._fetch_page(
                        client, endpoint, timestamp_from, timestamp_until, offset
                    )
                except httpx.HTTPStatusError as e:
                    logger.error(
                        "api_error",
                        endpoint=endpoint,
                        status=e.response.status_code,
                        detail=e.response.text[:200],
                    )
                    raise

                if not response.results:
                    break

                for reading in response.results:
                    yield reading
                    total_yielded += 1

                page_count += 1

                if response.count < self.page_size:
                    break

                offset += self.page_size

            logger.info(
                "fetch_window_complete",
                endpoint=endpoint,
                window_from=timestamp_from.strftime("%Y-%m-%d"),
                window_until=timestamp_until.strftime("%Y-%m-%d"),
                pages=page_count,
                records=total_yielded,
            )
