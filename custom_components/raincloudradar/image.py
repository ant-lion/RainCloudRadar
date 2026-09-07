"""Image platform showing the rain radar picture."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RainCloudRadarConfigEntry
from .coordinator import RadarImageProvider, RainCloudRadarCoordinator
from .entity import RainCloudRadarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RainCloudRadarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the radar image entity."""
    data = entry.runtime_data
    async_add_entities(
        [RainCloudRadarImage(hass, data.coordinator, data.provider, entry.entry_id)]
    )


class RainCloudRadarImage(RainCloudRadarEntity, ImageEntity):
    """The latest radar picture as an image entity."""

    _attr_content_type = "image/png"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: RainCloudRadarCoordinator,
        provider: RadarImageProvider,
        entry_id: str,
    ) -> None:
        """Initialise the image entity."""
        ImageEntity.__init__(self, hass)
        RainCloudRadarEntity.__init__(self, coordinator, provider, entry_id, "radar")
        self._update_timestamp()

    @callback
    def _update_timestamp(self) -> None:
        """Publish the frame time so the frontend reloads the picture."""
        if frame := self.coordinator.current_frame:
            self._attr_image_last_updated = frame.valid_time

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle a new set of frames."""
        self._update_timestamp()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the rendered radar picture."""
        return await self._provider.async_image()
