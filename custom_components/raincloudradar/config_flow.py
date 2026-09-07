"""Config and options flow for Rain Cloud Radar."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    LocationSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    BASE_MAP_CUSTOM,
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
    DOMAIN,
    MAX_FORECAST_OFFSET,
    MAX_SIZE,
    MAX_ZOOM,
    MIN_SIZE,
    MIN_ZOOM,
    SOURCES,
)
from .sources import SourceError, create_source

_LOGGER = logging.getLogger(__name__)

_SOURCE_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=SOURCES, mode=SelectSelectorMode.DROPDOWN, translation_key="source"
    )
)
_BASE_MAP_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=list(BASE_MAPS),
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="base_map",
    )
)
_COLOR_SCHEME_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[str(value) for value in range(9)],
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="color_scheme",
    )
)


def _zoom_selector() -> NumberSelector:
    """Return the zoom slider."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_ZOOM, max=MAX_ZOOM, step=1, mode=NumberSelectorMode.SLIDER
        )
    )


def _size_selector() -> NumberSelector:
    """Return a selector for one of the picture dimensions."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_SIZE,
            max=MAX_SIZE,
            step=16,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="px",
        )
    )


async def _async_validate_source(
    hass: HomeAssistant, source_key: str, color_scheme: int
) -> None:
    """Raise :class:`SourceError` when the provider cannot be reached."""
    source = create_source(source_key, color_scheme=color_scheme)
    session = async_get_clientsession(hass)
    frames = await source.async_get_frames(session)
    if not frames:
        raise SourceError("The provider did not return any radar frame")


def _validate_base_map(user_input: dict[str, Any]) -> dict[str, str]:
    """Check the custom tile template and return per-field errors."""
    if user_input.get(CONF_BASE_MAP) != BASE_MAP_CUSTOM:
        return {}
    url = (user_input.get(CONF_CUSTOM_BASE_MAP_URL) or "").strip()
    if not all(token in url for token in ("{z}", "{x}", "{y}")):
        return {CONF_CUSTOM_BASE_MAP_URL: "invalid_tile_url"}
    return {}


class RainCloudRadarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of a radar view."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the location and the radar provider."""
        errors: dict[str, str] = {}

        if user_input is not None:
            location = user_input[CONF_LOCATION]
            latitude = location[CONF_LATITUDE]
            longitude = location[CONF_LONGITUDE]
            source_key = user_input[CONF_SOURCE]
            zoom = int(user_input[CONF_ZOOM])

            await self.async_set_unique_id(
                f"{source_key}_{latitude:.4f}_{longitude:.4f}_{zoom}"
            )
            self._abort_if_unique_id_configured()

            try:
                await _async_validate_source(
                    self.hass, source_key, DEFAULT_COLOR_SCHEME
                )
            except SourceError as err:
                _LOGGER.debug("Radar provider %s unreachable: %s", source_key, err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        suggested = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=suggested.get(CONF_NAME, DEFAULT_NAME)
                    ): TextSelector(),
                    vol.Required(
                        CONF_SOURCE, default=suggested.get(CONF_SOURCE, DEFAULT_SOURCE)
                    ): _SOURCE_SELECTOR,
                    vol.Required(
                        CONF_LOCATION,
                        default=suggested.get(
                            CONF_LOCATION,
                            {
                                CONF_LATITUDE: self.hass.config.latitude,
                                CONF_LONGITUDE: self.hass.config.longitude,
                            },
                        ),
                    ): LocationSelector(),
                    vol.Required(
                        CONF_ZOOM, default=suggested.get(CONF_ZOOM, DEFAULT_ZOOM)
                    ): _zoom_selector(),
                    vol.Required(
                        CONF_WIDTH, default=suggested.get(CONF_WIDTH, DEFAULT_WIDTH)
                    ): _size_selector(),
                    vol.Required(
                        CONF_HEIGHT, default=suggested.get(CONF_HEIGHT, DEFAULT_HEIGHT)
                    ): _size_selector(),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return RainCloudRadarOptionsFlow(config_entry)


class RainCloudRadarOptionsFlow(OptionsFlow):
    """Let the user fine tune an existing radar view."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Remember the entry that is being edited."""
        # Assigning to ``self.config_entry`` is deprecated, keep our own name.
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_base_map(user_input)
            if not errors:
                user_input[CONF_COLOR_SCHEME] = int(user_input[CONF_COLOR_SCHEME])
                return self.async_create_entry(data=user_input)

        current: dict[str, Any] = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            current.update(user_input)
        source = create_source(current.get(CONF_SOURCE, DEFAULT_SOURCE))

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOURCE, default=current.get(CONF_SOURCE, DEFAULT_SOURCE)
                ): _SOURCE_SELECTOR,
                vol.Required(
                    CONF_LOCATION,
                    default=current.get(
                        CONF_LOCATION,
                        {
                            CONF_LATITUDE: self.hass.config.latitude,
                            CONF_LONGITUDE: self.hass.config.longitude,
                        },
                    ),
                ): LocationSelector(),
                vol.Required(
                    CONF_ZOOM, default=current.get(CONF_ZOOM, DEFAULT_ZOOM)
                ): _zoom_selector(),
                vol.Required(
                    CONF_WIDTH, default=current.get(CONF_WIDTH, DEFAULT_WIDTH)
                ): _size_selector(),
                vol.Required(
                    CONF_HEIGHT, default=current.get(CONF_HEIGHT, DEFAULT_HEIGHT)
                ): _size_selector(),
                vol.Required(
                    CONF_BASE_MAP,
                    default=current.get(CONF_BASE_MAP, source.default_base_map),
                ): _BASE_MAP_SELECTOR,
                vol.Optional(
                    CONF_CUSTOM_BASE_MAP_URL,
                    default=current.get(CONF_CUSTOM_BASE_MAP_URL, ""),
                ): TextSelector(),
                vol.Required(
                    CONF_OPACITY, default=current.get(CONF_OPACITY, DEFAULT_OPACITY)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1, max=1.0, step=0.05, mode=NumberSelectorMode.SLIDER
                    )
                ),
                vol.Required(
                    CONF_FORECAST_OFFSET,
                    default=current.get(CONF_FORECAST_OFFSET, DEFAULT_FORECAST_OFFSET),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=MAX_FORECAST_OFFSET,
                        step=5,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=60,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_SHOW_MARKER,
                    default=current.get(CONF_SHOW_MARKER, DEFAULT_SHOW_MARKER),
                ): BooleanSelector(),
                vol.Required(
                    CONF_SHOW_CAPTION,
                    default=current.get(CONF_SHOW_CAPTION, DEFAULT_SHOW_CAPTION),
                ): BooleanSelector(),
                vol.Required(
                    CONF_COLOR_SCHEME,
                    default=str(current.get(CONF_COLOR_SCHEME, DEFAULT_COLOR_SCHEME)),
                ): _COLOR_SCHEME_SELECTOR,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
