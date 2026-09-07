"""The Rain Cloud Radar integration.

Renders a rain radar picture centred on a location so it can be shown on a
Home Assistant dashboard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import RadarImageProvider, RainCloudRadarCoordinator
from .models import RadarConfig
from .sources import SourceError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CAMERA, Platform.IMAGE]


@dataclass
class RainCloudRadarData:
    """Runtime objects shared by the platforms of one config entry."""

    config: RadarConfig
    coordinator: RainCloudRadarCoordinator
    provider: RadarImageProvider


#: Config entry carrying our runtime data.
RainCloudRadarConfigEntry = ConfigEntry[RainCloudRadarData]


async def async_setup_entry(
    hass: HomeAssistant, entry: RainCloudRadarConfigEntry
) -> bool:
    """Set up Rain Cloud Radar from a config entry."""
    try:
        config = RadarConfig.from_entry(entry)
        source = config.create_source()
    except SourceError as err:
        _LOGGER.error("Invalid configuration for %s: %s", entry.title, err)
        return False

    coordinator = RainCloudRadarCoordinator(hass, config, source)
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        raise ConfigEntryNotReady(f"{source.label} did not return any radar frame yet")

    entry.runtime_data = RainCloudRadarData(
        config=config,
        coordinator=coordinator,
        provider=RadarImageProvider(hass, coordinator),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RainCloudRadarConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and hasattr(entry, "runtime_data"):
        entry.runtime_data.provider.clear()
    return unloaded


async def async_reload_entry(
    hass: HomeAssistant, entry: RainCloudRadarConfigEntry
) -> None:
    """Reload the entry after its options changed."""
    await hass.config_entries.async_reload(entry.entry_id)
