"""Tests for the slippy map helpers."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.raincloudradar.tiles import (
    TILE_SIZE,
    TileCache,
    TileFetcher,
    build_tile_grid,
    format_tile_url,
    latlon_to_world_pixel,
    world_pixel_to_latlon,
)

TILE_URL = "https://tiles.example/{z}/{x}/{y}.png"


def test_null_island_is_the_centre_of_the_world() -> None:
    """0/0 sits exactly in the middle of the world map."""
    x, y = latlon_to_world_pixel(0.0, 0.0, 0)
    assert (round(x, 6), round(y, 6)) == (TILE_SIZE / 2, TILE_SIZE / 2)


@pytest.mark.parametrize(
    ("latitude", "longitude", "zoom"),
    [(35.681236, 139.767125, 9), (-33.87, 151.21, 12), (51.5, -0.12, 4)],
)
def test_projection_round_trips(latitude: float, longitude: float, zoom: int) -> None:
    """Projecting and unprojecting a location returns the same point."""
    x, y = latlon_to_world_pixel(latitude, longitude, zoom)
    back_lat, back_lon = world_pixel_to_latlon(x, y, zoom)
    assert back_lat == pytest.approx(latitude, abs=1e-6)
    assert back_lon == pytest.approx(longitude, abs=1e-6)


def test_format_tile_url_supports_tms() -> None:
    """Both XYZ and the flipped TMS row are substituted."""
    assert format_tile_url(TILE_URL, 3, 1, 2) == "https://tiles.example/3/1/2.png"
    assert format_tile_url("{z}/{x}/{-y}", 3, 1, 2) == "3/1/5"


def test_grid_covers_the_whole_picture() -> None:
    """Every pixel of the requested picture is covered by exactly one tile."""
    width, height = 640, 480
    grid = build_tile_grid(35.681236, 139.767125, 9, width, height)

    assert grid.placements
    covered = set()
    for placement in grid:
        for x in range(placement.left, placement.left + TILE_SIZE):
            for y in range(placement.top, placement.top + TILE_SIZE):
                if 0 <= x < width and 0 <= y < height:
                    assert (x, y) not in covered
                    covered.add((x, y))
    assert len(covered) == width * height


def test_grid_wraps_around_the_antimeridian() -> None:
    """Tiles east of the antimeridian continue with column 0."""
    grid = build_tile_grid(0.0, 179.99, 2, 512, 256)
    columns = [placement.x for placement in grid]

    # Column 4 does not exist at zoom 2, it is the same tile as column 0.
    assert set(columns) == {2, 3, 0}
    assert all(0 <= placement.x < 4 for placement in grid)


def test_grid_skips_rows_beyond_the_poles() -> None:
    """Rows outside the map are dropped instead of being requested."""
    grid = build_tile_grid(85.0, 0.0, 1, 512, 512)
    assert all(0 <= placement.y < 2 for placement in grid)


def test_cache_expires_entries() -> None:
    """A stored tile disappears once its TTL passed."""
    cache = TileCache()
    cache.set("a", b"data", ttl=60)
    assert cache.get("a") == (True, b"data")

    cache.set("b", b"data", ttl=-1)
    assert cache.get("b") == (False, None)


def test_cache_remembers_missing_tiles() -> None:
    """A tile that does not exist is remembered as a hit without data."""
    cache = TileCache()
    cache.set("a", None, ttl=60)
    assert cache.get("a") == (True, None)


def test_cache_evicts_the_oldest_entry() -> None:
    """The cache never grows past its limit."""
    cache = TileCache(max_entries=2)
    cache.set("a", b"1", ttl=60)
    cache.set("b", b"2", ttl=60)
    cache.set("c", b"3", ttl=60)
    assert len(cache) == 2
    assert cache.get("a") == (False, None)


async def test_fetcher_caches_and_deduplicates(aioclient_mock, hass) -> None:
    """Tiles are fetched once and then served from the cache."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    aioclient_mock.get("https://tiles.example/1/0/0.png", content=b"tile")
    fetcher = TileFetcher(async_get_clientsession(hass), user_agent="test")

    first, second = await asyncio.gather(
        fetcher.async_fetch("https://tiles.example/1/0/0.png", 60),
        fetcher.async_fetch("https://tiles.example/1/0/0.png", 60),
    )

    assert first == second == b"tile"
    assert await fetcher.async_fetch("https://tiles.example/1/0/0.png", 60) == b"tile"
    assert aioclient_mock.call_count == 1


async def test_fetcher_treats_404_as_an_empty_tile(aioclient_mock, hass) -> None:
    """Providers answer 404 where there is no echo, which is not an error."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    aioclient_mock.get("https://tiles.example/1/0/0.png", status=404)
    fetcher = TileFetcher(async_get_clientsession(hass), user_agent="test")

    assert await fetcher.async_fetch("https://tiles.example/1/0/0.png", 60) is None
    # The negative result is cached as well.
    assert await fetcher.async_fetch("https://tiles.example/1/0/0.png", 60) is None
    assert aioclient_mock.call_count == 1


async def test_fetcher_does_not_cache_transport_errors(aioclient_mock, hass) -> None:
    """A failed request is retried on the next render."""
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    aioclient_mock.get(
        "https://tiles.example/1/0/0.png", exc=aiohttp.ClientError("boom")
    )
    fetcher = TileFetcher(async_get_clientsession(hass), user_agent="test")

    assert await fetcher.async_fetch("https://tiles.example/1/0/0.png", 60) is None
    assert await fetcher.async_fetch("https://tiles.example/1/0/0.png", 60) is None
    assert aioclient_mock.call_count == 2


async def test_fetch_grid_returns_only_existing_tiles(aioclient_mock, hass) -> None:
    """Missing tiles are left out of the result."""
    import re

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    grid = build_tile_grid(0.0, 0.0, 1, 512, 256)
    aioclient_mock.get("https://tiles.example/1/0/0.png", content=b"tile")
    # Every other tile of the grid has no data.
    aioclient_mock.get(re.compile(r"https://tiles\.example/.*"), status=404)
    fetcher = TileFetcher(async_get_clientsession(hass), user_agent="test")

    tiles = await fetcher.async_fetch_grid(TILE_URL, grid, 60)

    assert tiles == {(0, 0): b"tile"}
