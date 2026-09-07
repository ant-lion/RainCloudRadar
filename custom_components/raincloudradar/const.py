"""Constants for the Rain Cloud Radar integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "raincloudradar"

DEFAULT_NAME: Final = "Rain Cloud Radar"

# --- Configuration keys -------------------------------------------------------

CONF_SOURCE: Final = "source"
CONF_LOCATION: Final = "location"
CONF_ZOOM: Final = "zoom"
CONF_WIDTH: Final = "width"
CONF_HEIGHT: Final = "height"
CONF_BASE_MAP: Final = "base_map"
CONF_CUSTOM_BASE_MAP_URL: Final = "custom_base_map_url"
CONF_OPACITY: Final = "opacity"
CONF_FORECAST_OFFSET: Final = "forecast_offset"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_SHOW_MARKER: Final = "show_marker"
CONF_SHOW_CAPTION: Final = "show_caption"
CONF_COLOR_SCHEME: Final = "color_scheme"
CONF_ENABLE_VIEWER: Final = "enable_viewer"
CONF_VIEWER_TOKEN: Final = "viewer_token"

# --- Sources ------------------------------------------------------------------

SOURCE_JMA: Final = "jma"
SOURCE_RAINVIEWER: Final = "rainviewer"
SOURCES: Final = [SOURCE_JMA, SOURCE_RAINVIEWER]

# --- Base maps ----------------------------------------------------------------

BASE_MAP_NONE: Final = "none"
BASE_MAP_CUSTOM: Final = "custom"

BASE_MAPS: Final[dict[str, dict[str, object]]] = {
    "gsi_pale": {
        "url": "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png",
        "attribution": "地理院タイル (GSI Japan)",
        "min_zoom": 2,
        "max_zoom": 18,
    },
    "gsi_std": {
        "url": "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png",
        "attribution": "地理院タイル (GSI Japan)",
        "min_zoom": 2,
        "max_zoom": 18,
    },
    "gsi_blank": {
        "url": "https://cyberjapandata.gsi.go.jp/xyz/blank/{z}/{x}/{y}.png",
        "attribution": "地理院タイル (GSI Japan)",
        "min_zoom": 5,
        "max_zoom": 14,
    },
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors",
        "min_zoom": 0,
        "max_zoom": 19,
    },
    "carto_light": {
        "url": "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors © CARTO",
        "min_zoom": 0,
        "max_zoom": 19,
    },
    "carto_dark": {
        "url": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors © CARTO",
        "min_zoom": 0,
        "max_zoom": 19,
    },
    BASE_MAP_NONE: {
        "url": None,
        "attribution": "",
        "min_zoom": 0,
        "max_zoom": 20,
    },
    BASE_MAP_CUSTOM: {
        "url": None,
        "attribution": "",
        "min_zoom": 0,
        "max_zoom": 20,
    },
}

# --- Defaults -----------------------------------------------------------------

DEFAULT_SOURCE: Final = SOURCE_JMA
DEFAULT_ZOOM: Final = 9
DEFAULT_WIDTH: Final = 640
DEFAULT_HEIGHT: Final = 480
DEFAULT_OPACITY: Final = 0.85
DEFAULT_FORECAST_OFFSET: Final = 0
DEFAULT_UPDATE_INTERVAL: Final = 5
DEFAULT_SHOW_MARKER: Final = True
DEFAULT_SHOW_CAPTION: Final = True
DEFAULT_COLOR_SCHEME: Final = 4
DEFAULT_ENABLE_VIEWER: Final = False

MIN_ZOOM: Final = 4
MAX_ZOOM: Final = 16
MIN_SIZE: Final = 256
MAX_SIZE: Final = 1920
MAX_FORECAST_OFFSET: Final = 60

# --- Interactive viewer -------------------------------------------------------

#: Path of the pan and pinch viewer page, embedded with an iframe card.
VIEWER_URL: Final = "/api/raincloudradar/{token}"
VIEWER_MIN_SIZE: Final = 128
VIEWER_MAX_SIZE: Final = 1600

# --- Internals ----------------------------------------------------------------

USER_AGENT: Final = (
    "HomeAssistant-RainCloudRadar/1.0 (+https://github.com/ant-lion/RainCloudRadar)"
)

#: Base map tiles are static, radar tiles are replaced every few minutes.
BASE_TILE_TTL: Final = 24 * 60 * 60
RADAR_TILE_TTL: Final = 15 * 60

ATTR_FRAME_TIME: Final = "frame_time"
ATTR_IS_FORECAST: Final = "is_forecast"
ATTR_SOURCE: Final = "source"
ATTR_ZOOM: Final = "zoom"
ATTR_RADAR_ZOOM: Final = "radar_zoom"
ATTR_VIEWER_URL: Final = "viewer_url"
