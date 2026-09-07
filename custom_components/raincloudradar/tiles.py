"""Slippy map tile helpers.

This module is deliberately free of Home Assistant imports so the geometry can
be unit tested on its own.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import aiohttp

_LOGGER = logging.getLogger(__name__)

#: Edge length in pixels of a tile in the canonical web-mercator tile scheme.
TILE_SIZE = 256

#: Web mercator cannot represent the poles, tiles stop just short of them.
MAX_LATITUDE = 85.05112878


def clamp(value: float, low: float, high: float) -> float:
    """Return ``value`` limited to the ``low``..``high`` range."""
    return max(low, min(high, value))


def latlon_to_world_pixel(
    latitude: float, longitude: float, zoom: int
) -> tuple[float, float]:
    """Convert WGS84 coordinates to pixel coordinates of the whole world map."""
    latitude = clamp(latitude, -MAX_LATITUDE, MAX_LATITUDE)
    longitude = ((longitude + 180.0) % 360.0) - 180.0
    scale = TILE_SIZE * (2**zoom)
    x = (longitude + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(latitude))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return x, y


def world_pixel_to_latlon(x: float, y: float, zoom: int) -> tuple[float, float]:
    """Convert whole world map pixel coordinates back to WGS84 coordinates."""
    scale = TILE_SIZE * (2**zoom)
    longitude = x / scale * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / scale
    latitude = math.degrees(math.atan(math.sinh(n)))
    return latitude, longitude


def format_tile_url(template: str, zoom: int, x: int, y: int) -> str:
    """Fill ``{z}``/``{x}``/``{y}`` (and TMS ``{-y}``) in a tile URL template."""
    return (
        template.replace("{z}", str(zoom))
        .replace("{x}", str(x))
        .replace("{y}", str(y))
        .replace("{-y}", str(2**zoom - 1 - y))
    )


@dataclass(frozen=True, slots=True)
class TilePlacement:
    """A single tile together with where it belongs on the canvas."""

    #: Tile column, already wrapped into the valid 0..2^zoom-1 range.
    x: int
    #: Tile row.
    y: int
    #: Left/top offset of the tile inside the rendered image, may be negative.
    left: int
    top: int

    @property
    def key(self) -> tuple[int, int, int, int]:
        """Return a key that is unique per placement."""
        return (self.x, self.y, self.left, self.top)


@dataclass(frozen=True, slots=True)
class TileGrid:
    """The set of tiles needed to cover a rendered map image."""

    zoom: int
    width: int
    height: int
    placements: tuple[TilePlacement, ...] = field(default=())

    def __iter__(self) -> Iterable[TilePlacement]:
        """Iterate over the placements."""
        return iter(self.placements)

    def __len__(self) -> int:
        """Return the number of tiles in the grid."""
        return len(self.placements)

    @property
    def unique_tiles(self) -> tuple[tuple[int, int], ...]:
        """Return the distinct ``(x, y)`` tiles, each fetched only once."""
        seen: dict[tuple[int, int], None] = {}
        for placement in self.placements:
            seen.setdefault((placement.x, placement.y), None)
        return tuple(seen)


def build_tile_grid(
    latitude: float, longitude: float, zoom: int, width: int, height: int
) -> TileGrid:
    """Return the tiles covering a ``width`` x ``height`` image around a point."""
    center_x, center_y = latlon_to_world_pixel(latitude, longitude, zoom)
    origin_x = center_x - width / 2
    origin_y = center_y - height / 2

    first_col = math.floor(origin_x / TILE_SIZE)
    last_col = math.floor((origin_x + width - 1) / TILE_SIZE)
    first_row = math.floor(origin_y / TILE_SIZE)
    last_row = math.floor((origin_y + height - 1) / TILE_SIZE)

    tile_count = 2**zoom
    placements: list[TilePlacement] = []
    for col in range(first_col, last_col + 1):
        for row in range(first_row, last_row + 1):
            if row < 0 or row >= tile_count:
                # Above the north pole / below the south pole: nothing to draw.
                continue
            placements.append(
                TilePlacement(
                    x=col % tile_count,
                    y=row,
                    left=round(col * TILE_SIZE - origin_x),
                    top=round(row * TILE_SIZE - origin_y),
                )
            )
    return TileGrid(zoom=zoom, width=width, height=height, placements=tuple(placements))


class TileCache:
    """A tiny in-memory TTL cache so repeated renders do not refetch tiles."""

    def __init__(self, max_entries: int = 512) -> None:
        """Initialise the cache."""
        self._max_entries = max_entries
        self._entries: dict[str, tuple[float, bytes | None]] = {}

    def get(self, url: str) -> tuple[bool, bytes | None]:
        """Return ``(hit, data)``; ``data`` is ``None`` for cached misses."""
        entry = self._entries.get(url)
        if entry is None:
            return False, None
        expires, data = entry
        if expires < time.monotonic():
            self._entries.pop(url, None)
            return False, None
        # Refresh insertion order so the entry survives pruning a bit longer.
        self._entries[url] = self._entries.pop(url)
        return True, data

    def set(self, url: str, data: bytes | None, ttl: float) -> None:
        """Store ``data`` for ``url``. ``None`` remembers "there is no tile"."""
        self._entries[url] = (time.monotonic() + ttl, data)
        while len(self._entries) > self._max_entries:
            self._entries.pop(next(iter(self._entries)))

    def clear(self) -> None:
        """Drop every cached tile."""
        self._entries.clear()

    def __len__(self) -> int:
        """Return the number of cached entries."""
        return len(self._entries)


class TileFetcher:
    """Fetch tiles over HTTP with a bounded amount of concurrency."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        user_agent: str,
        cache: TileCache | None = None,
        timeout: float = 20.0,
        max_concurrency: int = 6,
    ) -> None:
        """Initialise the fetcher."""
        self._session = session
        self._user_agent = user_agent
        self._cache = cache if cache is not None else TileCache()
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def cache(self) -> TileCache:
        """Return the backing cache."""
        return self._cache

    async def async_fetch(self, url: str, ttl: float) -> bytes | None:
        """Return the tile bytes, or ``None`` when the tile does not exist.

        Radar providers answer 404 for tiles without any echo, which is a normal
        result rather than an error, so missing tiles are cached as well.
        """
        hit, cached = self._cache.get(url)
        if hit:
            return cached

        async with self._semaphore:
            # Another waiter may have populated the cache while we queued.
            hit, cached = self._cache.get(url)
            if hit:
                return cached
            try:
                response = await self._session.get(
                    url,
                    headers={"User-Agent": self._user_agent},
                    timeout=self._timeout,
                )
                async with response:
                    if response.status == 404:
                        self._cache.set(url, None, ttl)
                        return None
                    response.raise_for_status()
                    data = await response.read()
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Failed to fetch tile %s: %s", url, err)
                # Do not cache transport failures, the next render should retry.
                return None

        self._cache.set(url, data, ttl)
        return data

    async def async_fetch_grid(
        self, template: str, grid: TileGrid, ttl: float
    ) -> dict[tuple[int, int], bytes]:
        """Fetch every distinct tile of ``grid`` and return the ones that exist."""
        tiles = grid.unique_tiles
        results = await asyncio.gather(
            *(
                self.async_fetch(format_tile_url(template, grid.zoom, x, y), ttl)
                for x, y in tiles
            )
        )
        return {tile: data for tile, data in zip(tiles, results, strict=True) if data}
