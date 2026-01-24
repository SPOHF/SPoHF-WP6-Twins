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


class SpoHFClient:
    """Async client for SPoHF sensor data API."""

    def __init__(self, base_url: str, token: str, page_size: int = 100):
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
            "size": self.page_size,
            "from": offset,
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
