"""Tests for the config and options flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.raincloudradar.const import (
    BASE_MAP_CUSTOM,
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
    DOMAIN,
    SOURCE_JMA,
)

from .fixtures import CONFIG_DATA, JMA_FORECASTS, JMA_OBSERVATIONS

USER_INPUT = {
    CONF_NAME: "雨雲レーダー",
    CONF_SOURCE: SOURCE_JMA,
    CONF_LOCATION: {"latitude": 35.681236, "longitude": 139.767125},
    CONF_ZOOM: 9,
    CONF_WIDTH: 640,
    CONF_HEIGHT: 480,
}


def _mock_jma(aioclient_mock) -> None:
    """Answer the two JMA indexes."""
    from custom_components.raincloudradar.sources import jma

    aioclient_mock.get(jma.OBSERVATION_INDEX, json=JMA_OBSERVATIONS)
    aioclient_mock.get(jma.FORECAST_INDEX, json=JMA_FORECASTS)


async def test_user_flow_creates_an_entry(hass: HomeAssistant, aioclient_mock) -> None:
    """The happy path stores the answers as the entry data."""
    _mock_jma(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch("custom_components.raincloudradar.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "雨雲レーダー"
    assert result["data"] == USER_INPUT


async def test_user_flow_reports_an_unreachable_provider(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A provider outage is shown on the form instead of creating an entry."""
    from custom_components.raincloudradar.sources import jma

    aioclient_mock.get(jma.OBSERVATION_INDEX, status=500)
    aioclient_mock.get(jma.FORECAST_INDEX, status=500)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    # The form can be submitted again once the provider recovers.
    aioclient_mock.clear_requests()
    _mock_jma(aioclient_mock)
    with patch("custom_components.raincloudradar.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_aborts_on_a_duplicate(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """The same provider, location and zoom is only set up once."""
    _mock_jma(aioclient_mock)
    MockConfigEntry(
        domain=DOMAIN,
        data=CONFIG_DATA,
        unique_id="jma_35.6812_139.7671_9",
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_stores_the_options(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Every option is written back to the entry."""
    _mock_jma(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG_DATA, unique_id="test")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    options = {
        CONF_SOURCE: SOURCE_JMA,
        CONF_LOCATION: {"latitude": 34.0, "longitude": 135.0},
        CONF_ZOOM: 8,
        CONF_WIDTH: 320,
        CONF_HEIGHT: 320,
        CONF_BASE_MAP: "osm",
        CONF_CUSTOM_BASE_MAP_URL: "",
        CONF_OPACITY: 0.5,
        CONF_FORECAST_OFFSET: 30,
        CONF_UPDATE_INTERVAL: 10,
        CONF_SHOW_MARKER: False,
        CONF_SHOW_CAPTION: False,
        CONF_COLOR_SCHEME: "2",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ZOOM] == 8
    assert entry.options[CONF_COLOR_SCHEME] == 2


async def test_options_flow_rejects_an_incomplete_custom_url(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A custom base map needs a real XYZ template."""
    _mock_jma(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG_DATA, unique_id="test")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SOURCE: SOURCE_JMA,
            CONF_LOCATION: {"latitude": 34.0, "longitude": 135.0},
            CONF_ZOOM: 8,
            CONF_WIDTH: 320,
            CONF_HEIGHT: 320,
            CONF_BASE_MAP: BASE_MAP_CUSTOM,
            CONF_CUSTOM_BASE_MAP_URL: "https://example.com/tiles.png",
            CONF_OPACITY: 0.5,
            CONF_FORECAST_OFFSET: 0,
            CONF_UPDATE_INTERVAL: 5,
            CONF_SHOW_MARKER: True,
            CONF_SHOW_CAPTION: True,
            CONF_COLOR_SCHEME: "4",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CUSTOM_BASE_MAP_URL: "invalid_tile_url"}
