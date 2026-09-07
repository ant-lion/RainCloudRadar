"""Japan Meteorological Agency (気象庁) high resolution nowcast tiles.

The agency publishes the "高解像度降水ナウキャスト" as XYZ tiles.  Two small
JSON indexes list which frames currently exist:

* ``targetTimes_N1.json`` - observations (``basetime`` equals ``validtime``)
* ``targetTimes_N2.json`` - forecasts up to an hour ahead

Tiles then live under
``/nowc/{basetime}/{member}/{validtime}/surf/hrpns/{z}/{x}/{y}.png`` where
``member`` is ``none`` for observations and ``immed`` for forecasts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp

from ..const import SOURCE_JMA, USER_AGENT
from .base import RadarFrame, RadarSource, SourceError

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc"
OBSERVATION_INDEX = f"{BASE_URL}/targetTimes_N1.json"
FORECAST_INDEX = f"{BASE_URL}/targetTimes_N2.json"
TILE_TEMPLATE = (
    BASE_URL + "/{basetime}/{member}/{validtime}/surf/hrpns/{{z}}/{{x}}/{{y}}.png"
)

#: The element name of the precipitation layer inside the JSON index.
ELEMENT = "hrpns"

TIME_FORMAT = "%Y%m%d%H%M%S"


def _parse_time(value: str) -> datetime:
    """Parse a JMA timestamp, which is always UTC."""
    return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=UTC)


def parse_target_times(payload: Any) -> list[RadarFrame]:
    """Turn a ``targetTimes`` document into radar frames.

    Unknown or malformed entries are skipped rather than failing the whole
    update; the index occasionally carries elements we do not render.
    """
    if not isinstance(payload, list):
        raise SourceError("Unexpected JMA index payload")

    frames: list[RadarFrame] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        basetime = entry.get("basetime")
        validtime = entry.get("validtime")
        if not isinstance(basetime, str) or not isinstance(validtime, str):
            continue
        elements = entry.get("elements")
        if isinstance(elements, list) and ELEMENT not in elements:
            continue
        try:
            base = _parse_time(basetime)
            valid = _parse_time(validtime)
        except ValueError:
            _LOGGER.debug("Skipping JMA entry with bad timestamps: %s", entry)
            continue

        member = "none" if basetime == validtime else "immed"
        frames.append(
            RadarFrame(
                valid_time=valid,
                base_time=base,
                is_forecast=valid > base,
                url_template=TILE_TEMPLATE.format(
                    basetime=basetime, member=member, validtime=validtime
                ),
            )
        )

    frames.sort(key=lambda frame: frame.valid_time)
    return frames


class JmaNowcastSource(RadarSource):
    """Radar frames from the JMA high resolution precipitation nowcast."""

    key = SOURCE_JMA
    label = "気象庁 高解像度降水ナウキャスト"
    attribution = "気象庁 (Japan Meteorological Agency)"
    homepage = "https://www.jma.go.jp/bosai/nowc/"
    min_zoom = 4
    max_zoom = 10
    default_base_map = "gsi_pale"
    max_forecast_minutes = 60

    def __init__(self, **_: Any) -> None:
        """Initialise the source; it has no user facing options."""

    async def _async_get_json(self, session: aiohttp.ClientSession, url: str) -> Any:
        """Fetch and decode one of the JSON indexes."""
        try:
            response = await session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=20),
            )
            async with response:
                response.raise_for_status()
                # The agency serves the index as text/plain.
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SourceError(f"Could not load {url}: {err}") from err

    async def async_get_frames(
        self, session: aiohttp.ClientSession
    ) -> list[RadarFrame]:
        """Return observation and forecast frames published by the JMA."""
        observations, forecasts = await asyncio.gather(
            self._async_get_json(session, OBSERVATION_INDEX),
            self._async_get_json(session, FORECAST_INDEX),
            return_exceptions=True,
        )

        if isinstance(observations, BaseException):
            # Without observations there is nothing sensible left to show.
            raise SourceError(str(observations)) from observations

        frames = parse_target_times(observations)
        if isinstance(forecasts, BaseException):
            _LOGGER.debug("JMA forecast index unavailable: %s", forecasts)
        else:
            known = {frame.key for frame in frames}
            frames.extend(
                frame
                for frame in parse_target_times(forecasts)
                if frame.key not in known
            )
            frames.sort(key=lambda frame: frame.valid_time)

        if not frames:
            raise SourceError("The JMA index did not contain any usable frame")
        return frames
