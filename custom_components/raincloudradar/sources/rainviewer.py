"""Worldwide radar frames from the public RainViewer API.

``https://api.rainviewer.com/public/weather-maps.json`` lists the past two
hours of radar composites plus a short nowcast.  Every entry carries a ``path``
that is combined with the announced tile host into a regular XYZ template.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp

from ..const import DEFAULT_COLOR_SCHEME, SOURCE_RAINVIEWER, USER_AGENT
from ..tiles import TILE_SIZE
from .base import RadarFrame, RadarSource, SourceError

_LOGGER = logging.getLogger(__name__)

INDEX_URL = "https://api.rainviewer.com/public/weather-maps.json"
FALLBACK_HOST = "https://tilecache.rainviewer.com"

#: Colour schemes offered by RainViewer, see their API documentation.
COLOR_SCHEMES = tuple(range(9))


def parse_weather_maps(
    payload: Any,
    *,
    color_scheme: int = DEFAULT_COLOR_SCHEME,
    smooth: bool = True,
    snow: bool = True,
) -> list[RadarFrame]:
    """Turn a ``weather-maps.json`` document into radar frames."""
    if not isinstance(payload, dict):
        raise SourceError("Unexpected RainViewer payload")

    host = payload.get("host") or FALLBACK_HOST
    radar = payload.get("radar")
    if not isinstance(radar, dict):
        raise SourceError("The RainViewer payload did not contain radar data")

    options = f"{int(smooth)}_{int(snow)}"
    frames: list[RadarFrame] = []
    for section, is_forecast in (("past", False), ("nowcast", True)):
        entries = radar.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            timestamp = entry.get("time")
            path = entry.get("path")
            if not isinstance(timestamp, int | float) or not isinstance(path, str):
                continue
            valid = datetime.fromtimestamp(int(timestamp), tz=UTC)
            frames.append(
                RadarFrame(
                    valid_time=valid,
                    base_time=valid,
                    is_forecast=is_forecast,
                    url_template=(
                        f"{host}{path}/{TILE_SIZE}/{{z}}/{{x}}/{{y}}"
                        f"/{color_scheme}/{options}.png"
                    ),
                )
            )

    frames.sort(key=lambda frame: frame.valid_time)
    return frames


class RainViewerSource(RadarSource):
    """Radar frames from RainViewer, covering most of the world."""

    key = SOURCE_RAINVIEWER
    label = "RainViewer"
    attribution = "RainViewer.com"
    homepage = "https://www.rainviewer.com/"
    min_zoom = 0
    max_zoom = 12
    default_base_map = "carto_light"
    max_forecast_minutes = 30

    def __init__(self, color_scheme: int = DEFAULT_COLOR_SCHEME, **_: Any) -> None:
        """Initialise the source with the requested colour scheme."""
        self._color_scheme = (
            color_scheme if color_scheme in COLOR_SCHEMES else DEFAULT_COLOR_SCHEME
        )

    async def async_get_frames(
        self, session: aiohttp.ClientSession
    ) -> list[RadarFrame]:
        """Return the frames currently advertised by RainViewer."""
        try:
            response = await session.get(
                INDEX_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=20),
            )
            async with response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SourceError(f"Could not load {INDEX_URL}: {err}") from err

        frames = parse_weather_maps(payload, color_scheme=self._color_scheme)
        if not frames:
            raise SourceError("RainViewer did not return any radar frame")
        _LOGGER.debug("RainViewer returned %s frames", len(frames))
        return frames
