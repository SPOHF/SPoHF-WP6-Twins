"""Tests for wp6_data.api.client — mock httpx.AsyncClient."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wp6_data.api.client import SpoHFClient, parse_api_timestamp

from .conftest import make_reading

# --- parse_api_timestamp ---


class TestParseApiTimestamp:
    def test_z_suffix(self):
        dt = parse_api_timestamp("2024-06-15T12:00:00Z")
        assert dt == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_offset_suffix(self):
        dt = parse_api_timestamp("2024-06-15T12:00:00+00:00")
        assert dt == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)


# --- SpoHFClient init ---


class TestClientInit:
    def test_trailing_slash_stripped(self):
        client = SpoHFClient("https://api.example.com/", "token")
        assert client.base_url == "https://api.example.com"

    def test_page_size_default(self):
        client = SpoHFClient("https://api.example.com", "token")
        assert client.page_size == 1000

    def test_custom_page_size(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=500)
        assert client.page_size == 500

    def test_auth_header_set(self):
        client = SpoHFClient("https://api.example.com", "my-token")
        assert client._headers["Authorization"] == "Bearer my-token"


# --- _fetch_page ---


def _mock_response(json_data, status=200):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    resp.text = ""
    return resp


class TestFetchPage:
    @pytest.mark.asyncio()
    async def test_success_path(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=10)
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        reading_data = {
            "sensor_id": "d1",
            "sensor_tag": "temp",
            "value": "21.5",
            "datetime_measure": "2024-06-15T12:00:00+00:00",
            "timestamp": "2024-06-15T12:00:01+00:00",
        }
        mock_http.get.return_value = _mock_response(
            {"results": [reading_data], "count": 1}
        )

        ts = datetime(2024, 6, 1, tzinfo=UTC)
        # Bypass tenacity retry for unit test
        result = await client._fetch_page.__wrapped__(client, mock_http, "yookr-data", ts, 0)
        assert len(result.results) == 1
        assert result.count == 1

    @pytest.mark.asyncio()
    async def test_correct_params_passed(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=50)
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.get.return_value = _mock_response({"results": [], "count": 0})

        ts = datetime(2024, 6, 1, tzinfo=UTC)
        await client._fetch_page.__wrapped__(client, mock_http, "ep1", ts, 100)

        call_kwargs = mock_http.get.call_args
        assert call_kwargs.kwargs["params"]["size"] == "50"
        assert call_kwargs.kwargs["params"]["from"] == "100"
        assert "api.example.com/api/v1/data/ep1" in call_kwargs.args[0]


# --- fetch_all_since ---


class TestFetchAllSince:
    @pytest.mark.asyncio()
    async def test_single_page(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=10)
        reading = make_reading()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [reading.model_dump(mode="json")],
            "count": 1,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("wp6_data.api.client.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = []
            async for r in client.fetch_all_since("ep1", datetime(2024, 1, 1, tzinfo=UTC)):
                results.append(r)

        assert len(results) == 1

    @pytest.mark.asyncio()
    async def test_empty_results(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [], "count": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch("wp6_data.api.client.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = []
            async for r in client.fetch_all_since("ep1", datetime(2024, 1, 1, tzinfo=UTC)):
                results.append(r)

        assert len(results) == 0

    @pytest.mark.asyncio()
    async def test_multi_page_pagination(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=1)

        r1 = make_reading(sensor_tag="a")
        r2 = make_reading(sensor_tag="b")

        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "results": [r1.model_dump(mode="json")],
            "count": 1,  # count == page_size => more pages
        }
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {
            "results": [r2.model_dump(mode="json")],
            "count": 0,  # count < page_size => last page
        }
        page2.raise_for_status = MagicMock()

        with patch("wp6_data.api.client.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get.side_effect = [page1, page2]
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = []
            async for r in client.fetch_all_since("ep1", datetime(2024, 1, 1, tzinfo=UTC)):
                results.append(r)

        assert len(results) == 2

    @pytest.mark.asyncio()
    async def test_max_pages_limit(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=1)

        reading = make_reading()
        full_page = MagicMock()
        full_page.status_code = 200
        full_page.json.return_value = {
            "results": [reading.model_dump(mode="json")],
            "count": 1,  # always indicates more pages
        }
        full_page.raise_for_status = MagicMock()

        with patch("wp6_data.api.client.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get.return_value = full_page
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = []
            async for r in client.fetch_all_since(
                "ep1", datetime(2024, 1, 1, tzinfo=UTC), max_pages=3
            ):
                results.append(r)

        # max_pages=3, but first page (page_count=0) + 3 more iterations = 4 pages total
        # Actually: while page_count < max_pages => pages 0,1,2 then page_count increments
        # page_count starts at 0, increments after each page, loop runs while < 3
        # So we get readings from pages at offset 0, 1, 2 = 3 iterations, then page_count=3 stops
        assert mock_http.get.call_count <= 4


# --- fetch_all_windowed ---


class TestFetchAllWindowed:
    @pytest.mark.asyncio()
    async def test_three_empty_windows_stop(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=10)

        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"results": [], "count": 0}
        empty_resp.raise_for_status = MagicMock()

        with patch("wp6_data.api.client.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get.return_value = empty_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = []
            async for r in client.fetch_all_windowed(
                "ep1", datetime(2024, 1, 1, tzinfo=UTC)
            ):
                results.append(r)

        assert len(results) == 0
        # Should stop after 3 consecutive empty windows
        assert mock_http.get.call_count == 3

    @pytest.mark.asyncio()
    async def test_callback_invocation(self):
        client = SpoHFClient("https://api.example.com", "token", page_size=10)
        reading = make_reading()

        page_with_data = MagicMock()
        page_with_data.status_code = 200
        page_with_data.json.return_value = {
            "results": [reading.model_dump(mode="json")],
            "count": 1,
        }
        page_with_data.raise_for_status = MagicMock()

        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"results": [], "count": 0}
        empty_resp.raise_for_status = MagicMock()

        # One window with data, then 3 empty to stop
        responses = [page_with_data, empty_resp, empty_resp, empty_resp]

        callback = MagicMock()

        with patch("wp6_data.api.client.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get.side_effect = responses
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = []
            async for r in client.fetch_all_windowed(
                "ep1",
                datetime(2024, 1, 1, tzinfo=UTC),
                on_window_complete=callback,
            ):
                results.append(r)

        assert len(results) == 1
        callback.assert_called_once()
