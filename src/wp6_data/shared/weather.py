"""OpenMeteo API client for solar radiation forecasts and historical data.

Twin-agnostic: the client takes latitude/longitude per instance, so both
red (DLI / solar radiation) and blue (GDD / temperature) use it. It lives in
``shared`` rather than ``red`` so blue does not functionally depend on red.
"""

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
import pandas as pd

# Default location: the red greenhouse coordinates. Callers needing a
# different site (e.g. blue's farm) pass latitude/longitude to OpenMeteoClient.
# Env var names keep the WP6_RED_ prefix for deployment compatibility — they
# are the default override knob, not a red-only coupling.
DEFAULT_LAT = float(os.getenv("WP6_RED_WEATHER_LAT", "51.033056"))
DEFAULT_LON = float(os.getenv("WP6_RED_WEATHER_LON", "6.613721"))

OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


@dataclass
class HourlyWeather:
    """Hourly weather data point."""

    datetime: datetime
    solar_radiation: float  # W/m²
    cloud_cover: float  # 0-100%
    temperature: float  # °C


@dataclass
class DailyForecast:
    """Daily weather forecast with hourly data."""

    date: date
    hourly: list[HourlyWeather]
    sunrise: datetime | None = None
    sunset: datetime | None = None

    @property
    def total_radiation(self) -> float:
        """Total daily solar radiation in Wh/m²."""
        return sum(h.solar_radiation for h in self.hourly)

    @property
    def avg_cloud_cover(self) -> float:
        """Average cloud cover percentage."""
        if not self.hourly:
            return 0.0
        return sum(h.cloud_cover for h in self.hourly) / len(self.hourly)


class OpenMeteoClient:
    """Client for OpenMeteo weather API.

    Fetches solar radiation forecasts and historical data for DLI optimization.
    """

    def __init__(
        self,
        latitude: float = DEFAULT_LAT,
        longitude: float = DEFAULT_LON,
        timeout: float = 30.0,
    ):
        self.latitude = latitude
        self.longitude = longitude
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_forecast(
        self, days: int = 7, past_days: int = 0,
    ) -> list[DailyForecast]:
        """Fetch solar radiation forecast for the next N days.

        Args:
            days: Number of days to forecast (1-16)
            past_days: Recent past days to also include (0-92), from the same
                forecast model — used to bridge the ~5-day lag of the ERA5
                archive up to today.

        Returns:
            List of DailyForecast objects with hourly data
        """
        client = await self._get_client()

        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": "shortwave_radiation,cloud_cover,temperature_2m",
            "daily": "sunrise,sunset",
            "forecast_days": min(days, 16),
            "timezone": "UTC",
        }
        if past_days:
            params["past_days"] = min(past_days, 92)

        response = await client.get(OPENMETEO_FORECAST_URL, params=params)
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    async def get_historical(
        self,
        start: date,
        end: date,
    ) -> list[DailyForecast]:
        """Fetch historical solar radiation data.

        Args:
            start: Start date
            end: End date (inclusive)

        Returns:
            List of DailyForecast objects with hourly data
        """
        client = await self._get_client()

        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": "shortwave_radiation,cloud_cover,temperature_2m",
            "daily": "sunrise,sunset",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "UTC",
        }

        response = await client.get(OPENMETEO_ARCHIVE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> list[DailyForecast]:
        """Parse OpenMeteo API response into DailyForecast objects."""
        hourly = data.get("hourly", {})
        daily = data.get("daily", {})

        times = hourly.get("time", [])
        radiation = hourly.get("shortwave_radiation", [])
        cloud = hourly.get("cloud_cover", [])
        temp = hourly.get("temperature_2m", [])

        sunrises = daily.get("sunrise", [])
        sunsets = daily.get("sunset", [])

        # Group by date
        daily_data: dict[date, list[HourlyWeather]] = {}

        for i, time_str in enumerate(times):
            dt = datetime.fromisoformat(time_str).replace(tzinfo=UTC)
            day = dt.date()

            if day not in daily_data:
                daily_data[day] = []

            daily_data[day].append(
                HourlyWeather(
                    datetime=dt,
                    solar_radiation=radiation[i] if i < len(radiation) else 0.0,
                    cloud_cover=cloud[i] if i < len(cloud) else 0.0,
                    temperature=temp[i] if i < len(temp) else 0.0,
                )
            )

        # Build DailyForecast objects
        forecasts = []
        for i, (day, hourly_list) in enumerate(sorted(daily_data.items())):
            sunrise = None
            sunset = None
            if i < len(sunrises) and sunrises[i]:
                sunrise = datetime.fromisoformat(sunrises[i]).replace(tzinfo=UTC)
            if i < len(sunsets) and sunsets[i]:
                sunset = datetime.fromisoformat(sunsets[i]).replace(tzinfo=UTC)

            forecasts.append(
                DailyForecast(
                    date=day,
                    hourly=hourly_list,
                    sunrise=sunrise,
                    sunset=sunset,
                )
            )

        return forecasts

    async def get_forecast_dataframe(self, days: int = 7) -> pd.DataFrame:
        """Get forecast as a pandas DataFrame.

        Returns:
            DataFrame with columns: datetime, solar_radiation, cloud_cover, temperature
        """
        forecasts = await self.get_forecast(days)
        return self._forecasts_to_dataframe(forecasts)

    async def get_historical_dataframe(self, start: date, end: date) -> pd.DataFrame:
        """Get historical data as a pandas DataFrame.

        Returns:
            DataFrame with columns: datetime, solar_radiation, cloud_cover, temperature
        """
        forecasts = await self.get_historical(start, end)
        return self._forecasts_to_dataframe(forecasts)

    async def get_historical_dataframe_multi(
        self,
        start: date,
        end: date,
        radiation_var: str = "shortwave_radiation",
        include_diffuse: bool = False,
    ) -> pd.DataFrame:
        """Get historical data with selectable radiation variable.

        Args:
            start: Start date
            end: End date
            radiation_var: One of:
                - shortwave_radiation (default, total solar)
                - direct_radiation (direct sunlight)
                - diffuse_radiation (scattered light)
                - direct_normal_irradiance (perpendicular to sun)
                - global_tilted_irradiance (for tilted surfaces)
            include_diffuse: If True, also fetch diffuse_radiation

        Returns:
            DataFrame with columns: datetime, solar_radiation (or direct_radiation),
            cloud_cover, temperature, and optionally diffuse_radiation
        """
        client = await self._get_client()

        # Build hourly variables list
        hourly_vars = [radiation_var, "cloud_cover", "temperature_2m"]
        if include_diffuse and radiation_var != "diffuse_radiation":
            hourly_vars.append("diffuse_radiation")

        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join(hourly_vars),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "UTC",
        }

        response = await client.get(OPENMETEO_ARCHIVE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        radiation = hourly.get(radiation_var, [])
        cloud = hourly.get("cloud_cover", [])
        temp = hourly.get("temperature_2m", [])
        diffuse = hourly.get("diffuse_radiation", []) if include_diffuse else []

        records = []
        for i, time_str in enumerate(times):
            record = {
                "datetime": datetime.fromisoformat(time_str).replace(tzinfo=UTC),
                "solar_radiation": radiation[i] if i < len(radiation) else 0.0,
                "cloud_cover": cloud[i] if i < len(cloud) else 0.0,
                "temperature": temp[i] if i < len(temp) else 0.0,
            }
            # Also store as direct_radiation if that's what was requested
            if radiation_var == "direct_radiation":
                record["direct_radiation"] = record["solar_radiation"]
            if include_diffuse:
                record["diffuse_radiation"] = diffuse[i] if i < len(diffuse) else 0.0
            records.append(record)

        df = pd.DataFrame(records)
        if not df.empty:
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        return df

    def _forecasts_to_dataframe(self, forecasts: list[DailyForecast]) -> pd.DataFrame:
        """Convert DailyForecast list to DataFrame."""
        records = []
        for forecast in forecasts:
            for h in forecast.hourly:
                records.append({
                    "datetime": h.datetime,
                    "solar_radiation": h.solar_radiation,
                    "cloud_cover": h.cloud_cover,
                    "temperature": h.temperature,
                })

        df = pd.DataFrame(records)
        if not df.empty:
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        return df


