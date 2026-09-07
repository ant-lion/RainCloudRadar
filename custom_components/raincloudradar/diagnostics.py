"""Diagnostics support for Rain Cloud Radar."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from . import RainCloudRadarConfigEntry
from .const import CONF_LOCATION

TO_REDACT = {CONF_LOCATION, CONF_LATITUDE, CONF_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RainCloudRadarConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    coordinator = data.coordinator
    frame = coordinator.current_frame

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "source": {
            "key": coordinator.source.key,
            "label": coordinator.source.label,
            "zoom_range": [coordinator.source.min_zoom, coordinator.source.max_zoom],
            "effective_zoom": data.config.effective_zoom(coordinator.source),
        },
        "frames": {
            "count": len(coordinator.data or []),
            "oldest": coordinator.data[0].valid_time.isoformat()
            if coordinator.data
            else None,
            "newest": coordinator.data[-1].valid_time.isoformat()
            if coordinator.data
            else None,
            "selected": {
                "valid_time": frame.valid_time.isoformat(),
                "is_forecast": frame.is_forecast,
            }
            if frame
            else None,
        },
        "base_map": {
            "key": data.config.base_map,
            "configured": data.config.base_map_url is not None,
        },
    }
