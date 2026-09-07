"""Resolved configuration for a Rain Cloud Radar entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME

from .const import (
    BASE_MAP_CUSTOM,
    BASE_MAP_NONE,
    BASE_MAPS,
    CONF_BASE_MAP,
    CONF_COLOR_SCHEME,
    CONF_CUSTOM_BASE_MAP_URL,
    CONF_FORECAST_OFFSET,
    CONF_HEIGHT,
    CONF_LOCATION,
    CONF_OPACITY,
    CONF_SHOW_CAPTION,
    CONF_SHOW_MARKER,
    CONF_SOURCE,
    CONF_UPDATE_INTERVAL,
    CONF_WIDTH,
    CONF_ZOOM,
    DEFAULT_COLOR_SCHEME,
    DEFAULT_FORECAST_OFFSET,
    DEFAULT_HEIGHT,
    DEFAULT_NAME,
    DEFAULT_OPACITY,
    DEFAULT_SHOW_CAPTION,
    DEFAULT_SHOW_MARKER,
    DEFAULT_SOURCE,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WIDTH,
    DEFAULT_ZOOM,
    MAX_SIZE,
    MIN_SIZE,
)
from .sources import RadarSource, create_source


@dataclass(frozen=True, slots=True)
class RadarConfig:
    """The options of one radar view, merged from data and options."""

    name: str
    source_key: str
    latitude: float
    longitude: float
    zoom: int
    width: int
    height: int
    base_map: str
    custom_base_map_url: str
    opacity: float
    forecast_offset: int
    update_interval: int
    show_marker: bool
    show_caption: bool
    color_scheme: int

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> RadarConfig:
        """Build the configuration from a config entry.

        Options take precedence over the data captured during setup.
        """
        merged: dict[str, Any] = {**entry.data, **entry.options}
        location = merged.get(CONF_LOCATION) or {}
        source_key = merged.get(CONF_SOURCE, DEFAULT_SOURCE)
        source = create_source(source_key, color_scheme=DEFAULT_COLOR_SCHEME)

        return cls(
            name=merged.get(CONF_NAME) or entry.title or DEFAULT_NAME,
            source_key=source_key,
            latitude=float(location.get(CONF_LATITUDE, 0.0)),
            longitude=float(location.get(CONF_LONGITUDE, 0.0)),
            zoom=int(merged.get(CONF_ZOOM, DEFAULT_ZOOM)),
            width=_clamp_size(merged.get(CONF_WIDTH, DEFAULT_WIDTH)),
            height=_clamp_size(merged.get(CONF_HEIGHT, DEFAULT_HEIGHT)),
            base_map=merged.get(CONF_BASE_MAP) or source.default_base_map,
            custom_base_map_url=merged.get(CONF_CUSTOM_BASE_MAP_URL, "") or "",
            opacity=float(merged.get(CONF_OPACITY, DEFAULT_OPACITY)),
            forecast_offset=int(
                merged.get(CONF_FORECAST_OFFSET, DEFAULT_FORECAST_OFFSET)
            ),
            update_interval=int(
                merged.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
            show_marker=bool(merged.get(CONF_SHOW_MARKER, DEFAULT_SHOW_MARKER)),
            show_caption=bool(merged.get(CONF_SHOW_CAPTION, DEFAULT_SHOW_CAPTION)),
            color_scheme=int(merged.get(CONF_COLOR_SCHEME, DEFAULT_COLOR_SCHEME)),
        )

    def create_source(self) -> RadarSource:
        """Instantiate the configured radar source."""
        return create_source(self.source_key, color_scheme=self.color_scheme)

    @property
    def base_map_url(self) -> str | None:
        """Return the tile template of the base map, if one is configured."""
        if self.base_map == BASE_MAP_NONE:
            return None
        if self.base_map == BASE_MAP_CUSTOM:
            return self.custom_base_map_url or None
        url = BASE_MAPS.get(self.base_map, {}).get("url")
        return url if isinstance(url, str) else None

    @property
    def base_map_attribution(self) -> str:
        """Return the credit line required by the base map provider."""
        if self.base_map in (BASE_MAP_NONE, BASE_MAP_CUSTOM):
            return ""
        attribution = BASE_MAPS.get(self.base_map, {}).get("attribution", "")
        return attribution if isinstance(attribution, str) else ""

    def effective_zoom(self, source: RadarSource) -> int:
        """Return the zoom both the radar source and the base map can serve."""
        low, high = source.min_zoom, source.max_zoom
        if self.base_map in BASE_MAPS and self.base_map not in (
            BASE_MAP_NONE,
            BASE_MAP_CUSTOM,
        ):
            limits = BASE_MAPS[self.base_map]
            low = max(low, int(limits.get("min_zoom", low)))  # type: ignore[arg-type]
            high = min(high, int(limits.get("max_zoom", high)))  # type: ignore[arg-type]
        return max(low, min(high, self.zoom))


def _clamp_size(value: Any) -> int:
    """Keep the requested image size within sane bounds."""
    return max(MIN_SIZE, min(MAX_SIZE, int(value)))
