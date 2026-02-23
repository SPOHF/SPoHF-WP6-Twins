"""SPoHF API client with pagination and retry logic."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

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
        timestamp: datetime,
        offset: int,
    ) -> ApiResponse:
        """Fetch a single page with retry logic."""
        url = f"{self.base_url}/api/v1/data/{endpoint}"
        params = {
            "timestamp": timestamp.isoformat(),
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

    async def fetch_all_since(
        self,
        endpoint: str,
        since: datetime,
        max_pages: int = 100,
    ) -> AsyncIterator[SensorReading]:
        """Paginate through all records since timestamp.

        Args:
            endpoint: API endpoint (e.g., "yookr-data")
            since: Fetch records with timestamp >= this value
            max_pages: Safety limit on pagination

        Yields:
            SensorReading objects
        """
        async with httpx.AsyncClient() as client:
            offset = 0
            page_count = 0
            total_yielded = 0

            while page_count < max_pages:
                try:
                    response = await self._fetch_page(client, endpoint, since, offset)
                except httpx.HTTPStatusError as e:
                    logger.error(
                        "api_error",
                        endpoint=endpoint,
                        status=e.response.status_code,
                        detail=e.response.text[:200],
                    )
                    raise

                if not response.results:
                    logger.debug("no_more_results", endpoint=endpoint, offset=offset)
                    break

                for reading in response.results:
                    yield reading
                    total_yielded += 1

                # Check if we've reached the last page
                if response.count < self.page_size:
                    break

                offset += self.page_size
                page_count += 1

            logger.info(
                "fetch_complete",
                endpoint=endpoint,
                pages=page_count + 1,
                records=total_yielded,
            )

    async def fetch_all_windowed(
        self,
        endpoint: str,
        since: datetime,
        max_windows: int = 1000,
        window_days: int = 1,
        on_window_complete: Callable[[datetime, int, int], None] | None = None,
    ) -> AsyncIterator[SensorReading]:
        """Fetch all records using timestamp windows.

        The API returns max 10k records per timestamp window, but different
        timestamp values access different data. This method iterates through
        time windows to fetch all historical data.

        Args:
            endpoint: API endpoint (e.g., "yookr-data")
            since: Start fetching from this timestamp
            max_windows: Safety limit on number of windows
            window_days: Days per window (1 for daily, 30 for monthly)

        Yields:
            SensorReading objects (may include duplicates across windows)
        """
        async with httpx.AsyncClient() as client:
            # Always start from 2024-01-01 for windowed fetch to get all historical data
            current_ts = datetime(2024, 1, 1, tzinfo=UTC)

            # End at tomorrow to catch all data
            end_ts = datetime.now(UTC) + timedelta(days=1)

            window_count = 0
            total_yielded = 0
            consecutive_empty = 0

            while current_ts < end_ts and window_count < max_windows:
                # Fetch all pages for this daily window
                offset = 0
                window_records = 0

                while True:
                    try:
                        response = await self._fetch_page(
                            client, endpoint, current_ts, offset
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
                        window_records += 1

                    if response.count < self.page_size:
                        break
                    offset += self.page_size

                if window_records > 0:
                    window_end = current_ts + timedelta(days=window_days - 1)
                    logger.info(
                        "window_progress",
                        endpoint=endpoint,
                        window_start=current_ts.strftime("%Y-%m-%d"),
                        window_end=window_end.strftime("%Y-%m-%d"),
                        window_records=window_records,
                        total_records=total_yielded,
                    )
                    if on_window_complete:
                        on_window_complete(current_ts, window_records, total_yielded)
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1

                # Stop if we've had 3 consecutive empty windows
                if consecutive_empty >= 3:
                    break

                # Move to next window
                current_ts = current_ts + timedelta(days=window_days)
                window_count += 1

            logger.info(
                "windowed_fetch_complete",
                endpoint=endpoint,
                windows=window_count,
                total_records=total_yielded,
            )
