"""Camera platform showing the rain radar picture."""

from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RainCloudRadarConfigEntry
from .coordinator import RadarImageProvider, RainCloudRadarCoordinator
from .entity import RainCloudRadarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RainCloudRadarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the radar camera entity."""
    data = entry.runtime_data
    async_add_entities(
        [RainCloudRadarCamera(data.coordinator, data.provider, entry.entry_id)]
    )


class RainCloudRadarCamera(RainCloudRadarEntity, Camera):
    """The radar picture exposed as a camera, for picture cards and snapshots."""

    def __init__(
        self,
        coordinator: RainCloudRadarCoordinator,
        provider: RadarImageProvider,
        entry_id: str,
    ) -> None:
        """Initialise the camera entity."""
        Camera.__init__(self)
        RainCloudRadarEntity.__init__(self, coordinator, provider, entry_id, "radar")
        # ``Camera`` keeps the content type in a plain attribute rather than in
        # an ``_attr_`` one, so it has to be set after its initialiser ran.
        self.content_type = "image/png"
        # The picture only changes when a new frame is published, so there is
        # no point in letting the frontend poll faster than that.
        self._attr_frame_interval = max(60.0, coordinator.config.update_interval * 60.0)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the rendered radar picture."""
        return await self._provider.async_image()
