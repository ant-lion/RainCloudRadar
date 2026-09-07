"""Compose the radar picture from base map and radar tiles.

Kept free of Home Assistant imports so it can be exercised directly in tests.
The Pillow work is synchronous and CPU bound, so callers are expected to hand
:func:`async_render` an executor.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from .tiles import TILE_SIZE, TileFetcher, TileGrid, build_tile_grid

_LOGGER = logging.getLogger(__name__)

BACKGROUND_COLOR = (233, 235, 238, 255)
MARKER_COLOR = (219, 68, 55, 255)
MARKER_OUTLINE = (255, 255, 255, 255)
TEXT_COLOR = (255, 255, 255, 255)
TEXT_BACKDROP = (0, 0, 0, 140)

#: Fonts tried in order for the caption.  The Latin ones come first because
#: they look better for plain ASCII; a caption with Japanese characters falls
#: through to a font that actually has those glyphs (see :func:`_load_font`).
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)

#: Directories scanned for a font with CJK glyphs when none of the candidates
#: above has them.  ``/config/fonts`` lets users drop their own font next to
#: their Home Assistant configuration.
FONT_DIRS = (
    "/config/fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/root/.fonts",
)
FONT_PATTERNS = ("*CJK*", "*Gothic*", "*gothic*", "*Mincho*", "*mincho*", "*zenhei*")

#: A code point that no font maps, used to recognise the "missing glyph" box.
MISSING_GLYPH = "\uffff"


@dataclass(frozen=True, slots=True)
class MapView:
    """The geographic window that gets rendered."""

    latitude: float
    longitude: float
    zoom: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """Everything needed to draw one radar picture."""

    view: MapView
    radar_url_template: str
    base_map_url_template: str | None = None
    #: How many zoom levels below the view the radar tiles come from.
    radar_zoom_out: int = 0
    opacity: float = 1.0
    show_marker: bool = True
    caption: str | None = None
    attribution: str | None = None
    base_tile_ttl: float = 86400.0
    radar_tile_ttl: float = 900.0


def _draws_glyph(font: Any, character: str) -> bool:
    """Return whether ``font`` has a real glyph for ``character``.

    A font without the character draws the same "missing glyph" box for every
    unknown code point, so rendering it next to a code point that no font maps
    tells the two cases apart.
    """
    from PIL import Image, ImageDraw

    def render(text: str) -> bytes:
        box = max(8, int(getattr(font, "size", 12)) * 2)
        image = Image.new("L", (box, box), 0)
        ImageDraw.Draw(image).text((0, 0), text, font=font, fill=255)
        return image.tobytes()

    try:
        return render(character) != render(MISSING_GLYPH)
    except (OSError, ValueError, UnicodeError):
        return False


def _iter_font_paths() -> Iterator[str]:
    """Yield the candidate fonts, then anything CJK looking on the system."""
    yield from FONT_CANDIDATES
    from pathlib import Path

    for directory in FONT_DIRS:
        root = Path(directory)
        try:
            if not root.is_dir():
                continue
            for pattern in FONT_PATTERNS:
                for suffix in ("ttf", "ttc", "otf", "otc"):
                    yield from (
                        str(path) for path in sorted(root.rglob(f"{pattern}.{suffix}"))
                    )
        except OSError:  # pragma: no cover - unreadable font directory
            continue


@lru_cache(maxsize=16)
def _load_font(size: int, sample: str | None = None) -> Any:
    """Return a font of roughly ``size`` pixels that can draw ``sample``.

    Home Assistant installations rarely ship a font with Japanese glyphs, so
    the first font able to draw the caption wins; if none can, the caption is
    still drawn (with boxes for the missing characters) rather than dropped.
    """
    from PIL import ImageFont

    fallback: Any = None
    for path in _iter_font_paths():
        try:
            font = ImageFont.truetype(path, size)
        except OSError:
            continue
        if sample is None or _draws_glyph(font, sample):
            return font
        if fallback is None:
            fallback = font

    if fallback is not None:
        return fallback
    try:
        # Pillow >= 10.1 can scale its built in font.
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _font_for(text: str, size: int) -> Any:
    """Return a font able to draw ``text`` at ``size`` pixels."""
    sample = next((char for char in text if ord(char) > 0x2E80), None)
    return _load_font(size, sample)


def _open_tile(data: bytes) -> Any | None:
    """Decode a tile and normalise it to an RGBA image of ``TILE_SIZE``."""
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as err:
        _LOGGER.debug("Ignoring undecodable tile: %s", err)
        return None

    if image.mode != "RGBA":
        image = image.convert("RGBA")
    if image.size != (TILE_SIZE, TILE_SIZE):
        # Retina tiles and other tile sizes are scaled onto our pixel grid.
        image = image.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS)
    return image


def _paste_layer(
    grid: TileGrid,
    tiles: dict[tuple[int, int], bytes],
    size: tuple[int, int],
    zoom_out: int = 0,
) -> Any:
    """Draw every available tile of ``grid`` onto a fresh transparent layer.

    ``zoom_out`` says how many zoom levels above the grid ``tiles`` were taken
    from: each placement then shows the matching quarter (or sixteenth, ...) of
    its coarser tile, magnified.  Nearest neighbour keeps the intensity colours
    of a radar image intact instead of inventing shades between the steps.
    """
    from PIL import Image

    zoom_out = max(0, zoom_out)
    factor = 1 << zoom_out
    span = max(1, TILE_SIZE // factor)

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    decoded: dict[tuple[int, int], Any] = {}
    prepared: dict[tuple[int, int], Any] = {}
    for placement in grid:
        parent = (placement.x >> zoom_out, placement.y >> zoom_out)
        data = tiles.get(parent)
        if data is None:
            continue
        if parent not in decoded:
            tile = _open_tile(data)
            if tile is None:
                continue
            decoded[parent] = tile
        if parent not in decoded:
            continue

        key = (placement.x, placement.y)
        if key not in prepared:
            if zoom_out == 0:
                prepared[key] = decoded[parent]
            else:
                left = (placement.x % factor) * span
                top = (placement.y % factor) * span
                prepared[key] = (
                    decoded[parent]
                    .crop((left, top, left + span, top + span))
                    .resize((TILE_SIZE, TILE_SIZE), Image.NEAREST)
                )
        layer.paste(prepared[key], (placement.left, placement.top))
    return layer


def _apply_opacity(layer: Any, opacity: float) -> Any:
    """Scale the alpha channel of ``layer`` by ``opacity``."""
    if opacity >= 1.0:
        return layer
    alpha = layer.getchannel("A").point(lambda value: int(value * opacity))
    layer.putalpha(alpha)
    return layer


def _draw_marker(canvas: Any) -> None:
    """Mark the centre of the picture, which is the configured location."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas)
    center_x = canvas.width // 2
    center_y = canvas.height // 2
    radius = 6
    draw.ellipse(
        [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
        fill=MARKER_COLOR,
        outline=MARKER_OUTLINE,
        width=2,
    )
    arm = radius * 3
    for start, end in (
        ((center_x - arm, center_y), (center_x - radius - 2, center_y)),
        ((center_x + radius + 2, center_y), (center_x + arm, center_y)),
        ((center_x, center_y - arm), (center_x, center_y - radius - 2)),
        ((center_x, center_y + radius + 2), (center_x, center_y + arm)),
    ):
        draw.line([start, end], fill=MARKER_OUTLINE, width=3)
        draw.line([start, end], fill=MARKER_COLOR, width=1)


def _draw_label(
    canvas: Any, text: str, *, size: int, top: bool, padding: int = 6
) -> None:
    """Draw ``text`` on a translucent bar at the top or bottom of the picture."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas)
    font = _font_for(text, size)
    left, top_box, _right, bottom = draw.textbbox((0, 0), text, font=font)
    text_height = bottom - top_box

    box_height = text_height + padding * 2
    if top:
        box = [0, 0, canvas.width, box_height]
        text_y = padding - top_box
    else:
        box = [0, canvas.height - box_height, canvas.width, canvas.height]
        text_y = canvas.height - box_height + padding - top_box

    draw.rectangle(box, fill=TEXT_BACKDROP)
    draw.text((padding - left, text_y), text, font=font, fill=TEXT_COLOR)


def compose(
    request: RenderRequest,
    grid: TileGrid,
    base_tiles: dict[tuple[int, int], bytes],
    radar_tiles: dict[tuple[int, int], bytes],
) -> bytes:
    """Return the finished picture as PNG bytes."""
    from PIL import Image

    size = (request.view.width, request.view.height)
    canvas = Image.new("RGBA", size, BACKGROUND_COLOR)

    if base_tiles:
        canvas = Image.alpha_composite(canvas, _paste_layer(grid, base_tiles, size))
    if radar_tiles:
        radar_layer = _apply_opacity(
            _paste_layer(grid, radar_tiles, size, request.radar_zoom_out),
            request.opacity,
        )
        canvas = Image.alpha_composite(canvas, radar_layer)

    if request.show_marker:
        _draw_marker(canvas)
    if request.caption:
        _draw_label(
            canvas,
            request.caption,
            size=max(12, request.view.width // 40),
            top=True,
        )
    if request.attribution:
        _draw_label(
            canvas,
            request.attribution,
            size=max(10, request.view.width // 64),
            top=False,
        )

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def async_render(
    fetcher: TileFetcher,
    request: RenderRequest,
    executor: Callable[..., Awaitable[bytes]] | None = None,
) -> bytes:
    """Fetch the tiles for ``request`` and compose them into a PNG.

    ``executor`` is Home Assistant's ``async_add_executor_job``; when omitted
    the (CPU bound) composition runs inline, which is handy for tests.
    """
    view = request.view
    grid = build_tile_grid(
        view.latitude, view.longitude, view.zoom, view.width, view.height
    )

    base_tiles: dict[tuple[int, int], bytes] = {}
    if request.base_map_url_template:
        base_tiles = await fetcher.async_fetch_grid(
            request.base_map_url_template, grid, request.base_tile_ttl
        )
    radar_tiles = await fetcher.async_fetch_grid(
        request.radar_url_template, grid, request.radar_tile_ttl, request.radar_zoom_out
    )

    if executor is None:
        return compose(request, grid, base_tiles, radar_tiles)
    return await executor(compose, request, grid, base_tiles, radar_tiles)


def format_caption(
    name: str, frame_time: datetime, is_forecast: bool, forecast_word: str = "forecast"
) -> str:
    """Return the caption drawn across the top of the picture."""
    stamp = frame_time.strftime("%Y-%m-%d %H:%M")
    if is_forecast:
        return f"{name}  {stamp}  ({forecast_word})"
    return f"{name}  {stamp}"
