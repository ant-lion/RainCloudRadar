"""The Rain Cloud Radar integration.

Renders a rain radar picture centred on a location so it can be shown on a
Home Assistant dashboard.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_VIEWER_TOKEN
from .coordinator import RadarImageProvider, RainCloudRadarCoordinator
from .models import RadarConfig
from .sources import SourceError
from .viewer import async_register_views

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
    if not entry.data.get(CONF_VIEWER_TOKEN):
        # The interactive viewer is reached without a Home Assistant login, so
        # it is guarded by an unguessable token, like a webhook. Generating it
        # here keeps entries created before the viewer existed working too.
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_VIEWER_TOKEN: secrets.token_hex(16)},
        )

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

    if config.viewer_enabled:
        async_register_views(hass)

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
