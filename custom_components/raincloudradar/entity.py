"""Shared entity plumbing for Rain Cloud Radar."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_FRAME_TIME,
    ATTR_IS_FORECAST,
    ATTR_RADAR_ZOOM,
    ATTR_SOURCE,
    ATTR_VIEWER_URL,
    ATTR_ZOOM,
    DOMAIN,
)
from .coordinator import RadarImageProvider, RainCloudRadarCoordinator
from .viewer import viewer_path


class RainCloudRadarEntity(CoordinatorEntity[RainCloudRadarCoordinator]):
    """Device info and state attributes shared by both radar entities.

    ``CoordinatorEntity.__init__`` is called explicitly rather than through
    ``super()`` because the concrete entities also inherit from ``Camera`` or
    ``ImageEntity``, which need their own initialiser to run.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RainCloudRadarCoordinator,
        provider: RadarImageProvider,
        entry_id: str,
        key: str,
    ) -> None:
        """Initialise the shared entity parts."""
        CoordinatorEntity.__init__(self, coordinator)
        self._provider = provider
        config = coordinator.config
        source = coordinator.source
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_attribution = source.attribution
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=config.name,
            manufacturer=source.attribution,
            model=source.label,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=source.homepage,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about the frame currently displayed."""
        coordinator = self.coordinator
        frame = coordinator.current_frame
        attributes: dict[str, Any] = {
            ATTR_SOURCE: coordinator.source.label,
            ATTR_ZOOM: coordinator.config.effective_zoom(coordinator.source),
            ATTR_RADAR_ZOOM: coordinator.config.radar_zoom(coordinator.source),
        }
        if frame is not None:
            attributes[ATTR_FRAME_TIME] = frame.valid_time.isoformat()
            attributes[ATTR_IS_FORECAST] = frame.is_forecast
        config = coordinator.config
        if config.viewer_enabled and config.viewer_token:
            attributes[ATTR_VIEWER_URL] = viewer_path(config.viewer_token)
        return attributes
