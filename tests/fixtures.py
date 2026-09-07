"""Sample payloads and helpers used by the tests."""

from __future__ import annotations

import io

from custom_components.raincloudradar.const import (
    CONF_HEIGHT,
    CONF_LOCATION,
    CONF_SOURCE,
    CONF_WIDTH,
    CONF_ZOOM,
    SOURCE_JMA,
)

#: Two observations followed by one forecast, in the shape the JMA publishes.
JMA_OBSERVATIONS = [
    {
        "basetime": "20250101000000",
        "validtime": "20250101000000",
        "elements": ["hrpns", "slmcs"],
    },
    {
        "basetime": "20250101000500",
        "validtime": "20250101000500",
        "elements": ["hrpns"],
    },
]
JMA_FORECASTS = [
    {
        "basetime": "20250101000500",
        "validtime": "20250101001000",
        "elements": ["hrpns"],
    },
    {
        "basetime": "20250101000500",
        "validtime": "20250101003500",
        "elements": ["hrpns"],
    },
]

RAINVIEWER_INDEX = {
    "version": "2.0",
    "generated": 1735689600,
    "host": "https://tilecache.rainviewer.com",
    "radar": {
        "past": [
            {"time": 1735689000, "path": "/v2/radar/1735689000"},
            {"time": 1735689600, "path": "/v2/radar/1735689600"},
        ],
        "nowcast": [{"time": 1735690200, "path": "/v2/radar/nowcast_abc"}],
    },
}

CONFIG_DATA = {
    "name": "Rain Cloud Radar",
    CONF_SOURCE: SOURCE_JMA,
    CONF_LOCATION: {"latitude": 35.681236, "longitude": 139.767125},
    CONF_ZOOM: 9,
    CONF_WIDTH: 512,
    CONF_HEIGHT: 384,
}


def png_bytes(color: tuple[int, int, int, int], size: int = 256) -> bytes:
    """Return a single colour PNG tile."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()
