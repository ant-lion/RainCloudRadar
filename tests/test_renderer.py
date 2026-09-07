"""Tests for composing the radar picture."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest

from custom_components.raincloudradar.renderer import (
    MapView,
    RenderRequest,
    async_render,
    compose,
    format_caption,
)
from custom_components.raincloudradar.tiles import TileFetcher, build_tile_grid

from .fixtures import png_bytes

BLUE = (0, 0, 255, 255)
RED = (255, 0, 0, 255)
VIEW = MapView(latitude=35.681236, longitude=139.767125, zoom=9, width=320, height=240)


def _open(data: bytes):
    """Open rendered PNG bytes as an image."""
    from PIL import Image

    return Image.open(io.BytesIO(data))


def _request(**kwargs) -> RenderRequest:
    """Build a render request with test friendly defaults."""
    options = {
        "view": VIEW,
        "radar_url_template": "https://radar.example/{z}/{x}/{y}.png",
        "base_map_url_template": "https://base.example/{z}/{x}/{y}.png",
        "show_marker": False,
        "caption": None,
        "attribution": None,
    }
    options.update(kwargs)
    return RenderRequest(**options)


def test_compose_returns_a_png_of_the_requested_size() -> None:
    """The rendered picture matches the configured dimensions."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )
    tiles = {tile: png_bytes(BLUE) for tile in grid.unique_tiles}

    image = _open(compose(_request(), grid, tiles, {}))

    assert image.format == "PNG"
    assert image.size == (VIEW.width, VIEW.height)
    assert image.convert("RGB").getpixel((10, 10)) == BLUE[:3]


def test_radar_tiles_are_drawn_over_the_base_map() -> None:
    """The radar layer wins where it has data."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )
    base = {tile: png_bytes(BLUE) for tile in grid.unique_tiles}
    radar = {tile: png_bytes(RED) for tile in grid.unique_tiles}

    image = _open(compose(_request(), grid, base, radar)).convert("RGB")

    assert image.getpixel((10, 10)) == RED[:3]


def test_opacity_blends_the_radar_layer() -> None:
    """A semi transparent radar layer mixes with the base map."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )
    base = {tile: png_bytes(BLUE) for tile in grid.unique_tiles}
    radar = {tile: png_bytes(RED) for tile in grid.unique_tiles}

    image = _open(compose(_request(opacity=0.5), grid, base, radar)).convert("RGB")
    red, green, blue = image.getpixel((10, 10))

    assert 100 < red < 160
    assert 100 < blue < 160
    assert green == 0


def test_missing_tiles_fall_back_to_the_background() -> None:
    """A picture is still produced when no tile could be fetched."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )

    image = _open(compose(_request(), grid, {}, {}))

    assert image.size == (VIEW.width, VIEW.height)


def test_undecodable_tiles_are_ignored() -> None:
    """An error page served instead of a tile does not break the render."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )
    tiles = {tile: b"<html>404</html>" for tile in grid.unique_tiles}

    image = _open(compose(_request(), grid, tiles, {}))

    assert image.size == (VIEW.width, VIEW.height)


def test_marker_and_labels_are_drawn() -> None:
    """The decorations change the picture without changing its size."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )
    tiles = {tile: png_bytes(BLUE) for tile in grid.unique_tiles}

    plain = compose(_request(), grid, tiles, {})
    decorated = compose(
        _request(show_marker=True, caption="Radar", attribution="Provider"),
        grid,
        tiles,
        {},
    )

    assert plain != decorated
    image = _open(decorated).convert("RGB")
    assert image.size == (VIEW.width, VIEW.height)
    # The marker sits in the middle and the caption bar at the top.
    assert image.getpixel((VIEW.width // 2, VIEW.height // 2)) != BLUE[:3]
    assert image.getpixel((2, 2)) != BLUE[:3]


def test_oversized_tiles_are_scaled_onto_the_grid() -> None:
    """Retina tiles are resized instead of shifting the map."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )
    tiles = {tile: png_bytes(BLUE, size=512) for tile in grid.unique_tiles}

    image = _open(compose(_request(), grid, tiles, {})).convert("RGB")

    assert image.getpixel((VIEW.width - 1, VIEW.height - 1)) == BLUE[:3]


def test_format_caption_marks_forecasts() -> None:
    """Forecast frames are labelled as such."""
    moment = datetime(2025, 1, 1, 9, 30, tzinfo=UTC)

    assert format_caption("Radar", moment, False) == "Radar  2025-01-01 09:30"
    assert (
        format_caption("Radar", moment, True, "予測")
        == "Radar  2025-01-01 09:30  (予測)"
    )


async def test_async_render_fetches_both_layers(aioclient_mock, hass) -> None:
    """Base map and radar tiles are requested and composed."""
    import re

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    aioclient_mock.get(re.compile(r"https://base\.example/.*"), content=png_bytes(BLUE))
    aioclient_mock.get(re.compile(r"https://radar\.example/.*"), content=png_bytes(RED))

    fetcher = TileFetcher(async_get_clientsession(hass), user_agent="test")
    image = _open(await async_render(fetcher, _request()))

    assert image.size == (VIEW.width, VIEW.height)
    assert image.convert("RGB").getpixel((10, 10)) == RED[:3]


async def test_async_render_without_a_base_map(aioclient_mock, hass) -> None:
    """No base map means no requests to a base map host."""
    import re

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    aioclient_mock.get(re.compile(r"https://radar\.example/.*"), content=png_bytes(RED))

    fetcher = TileFetcher(async_get_clientsession(hass), user_agent="test")
    await async_render(fetcher, _request(base_map_url_template=None))

    assert all("base.example" not in str(call[1]) for call in aioclient_mock.mock_calls)


def test_font_selection_skips_fonts_without_the_glyph() -> None:
    """A Latin only font is not used to draw Japanese characters."""
    from pathlib import Path

    from PIL import ImageFont

    from custom_components.raincloudradar.renderer import _draws_glyph, _font_for

    latin_only = next(
        (
            path
            for path in (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            )
            if Path(path).is_file()
        ),
        None,
    )
    if latin_only is None:
        pytest.skip("no Latin font available in this environment")

    font = ImageFont.truetype(latin_only, 16)
    assert _draws_glyph(font, "A")
    assert not _draws_glyph(font, "雨")

    # The caption font is picked per text: ASCII keeps a Latin font, and where
    # the system has a font with Japanese glyphs the caption switches to it.
    ascii_font = _font_for("Radar", 16)
    assert _draws_glyph(ascii_font, "A")

    japanese_font = _font_for("雨雲レーダー", 16)
    if _draws_glyph(japanese_font, "雨"):
        assert japanese_font.path != ascii_font.path


def test_caption_with_japanese_is_drawn() -> None:
    """A Japanese caption produces visible pixels on the caption bar."""
    grid = build_tile_grid(
        VIEW.latitude, VIEW.longitude, VIEW.zoom, VIEW.width, VIEW.height
    )
    tiles = {tile: png_bytes(BLUE) for tile in grid.unique_tiles}

    without = compose(_request(caption=None), grid, tiles, {})
    with_caption = compose(_request(caption="雨雲レーダー 09:05"), grid, tiles, {})

    assert without != with_caption
