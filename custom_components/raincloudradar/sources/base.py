"""Common types shared by the radar tile providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp


class SourceError(Exception):
    """Raised when a radar provider cannot be queried or understood."""


@dataclass(frozen=True, slots=True)
class RadarFrame:
    """A single radar image in time, published as a set of map tiles."""

    #: The moment the frame describes, in UTC.
    valid_time: datetime
    #: The observation the frame was derived from, in UTC.
    base_time: datetime
    #: ``True`` for nowcast frames that lie in the future.
    is_forecast: bool
    #: Tile URL template containing ``{z}``, ``{x}`` and ``{y}`` placeholders.
    url_template: str

    @property
    def key(self) -> str:
        """Return a stable identifier used to cache rendered images."""
        return self.url_template


class RadarSource(ABC):
    """Interface implemented by every radar tile provider."""

    #: Identifier stored in the config entry.
    key: str = ""
    #: Human readable provider name, also used as the credit line.
    label: str = ""
    #: Attribution that has to be shown together with the imagery.
    attribution: str = ""
    #: Provider homepage, linked from the Home Assistant device page.
    homepage: str = ""
    #: Zoom levels the provider publishes tiles for.
    min_zoom: int = 0
    max_zoom: int = 12
    #: Base map that pairs best with this provider.
    default_base_map: str = "osm"
    #: Longest look ahead the provider offers, in minutes.
    max_forecast_minutes: int = 0

    def clamp_zoom(self, zoom: int) -> int:
        """Return ``zoom`` limited to the range the provider publishes."""
        return max(self.min_zoom, min(self.max_zoom, zoom))

    @abstractmethod
    async def async_get_frames(
        self, session: aiohttp.ClientSession
    ) -> list[RadarFrame]:
        """Return the available frames, ordered from oldest to newest."""

    @staticmethod
    def select_frame(
        frames: list[RadarFrame], now: datetime, offset_minutes: int = 0
    ) -> RadarFrame | None:
        """Pick the frame that best matches ``now`` plus ``offset_minutes``.

        With no offset the most recent observation is used; observations are
        preferred over nowcasts so a fresh forecast never hides reality.
        """
        if not frames:
            return None

        if offset_minutes <= 0:
            observations = [frame for frame in frames if not frame.is_forecast]
            candidates = observations or frames
            return max(candidates, key=lambda frame: frame.valid_time)

        target = now + timedelta(minutes=offset_minutes)
        return min(
            frames, key=lambda frame: abs((frame.valid_time - target).total_seconds())
        )
