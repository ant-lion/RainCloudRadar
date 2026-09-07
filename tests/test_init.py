"""Tests for setting up the integration and its entities."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.raincloudradar.const import (
    ATTR_FRAME_TIME,
    ATTR_IS_FORECAST,
    ATTR_RADAR_ZOOM,
    ATTR_ZOOM,
    CONF_BASE_MAP,
    CONF_FORECAST_OFFSET,
    CONF_ZOOM,
    DOMAIN,
)
from custom_components.raincloudradar.models import RadarConfig

from .fixtures import CONFIG_DATA, JMA_FORECASTS, JMA_OBSERVATIONS, png_bytes

CAMERA_ENTITY = "camera.rain_cloud_radar_radar"
IMAGE_ENTITY = "image.rain_cloud_radar_radar"

RADAR_TILE = re.compile(r"https://www\.jma\.go\.jp/bosai/jmatile/data/nowc/.*\.png")
BASE_TILE = re.compile(r"https://cyberjapandata\.gsi\.go\.jp/.*\.png")


@pytest.fixture(name="mock_jma")
def mock_jma_fixture(aioclient_mock):
    """Answer the JMA indexes and every tile request."""
    from custom_components.raincloudradar.sources import jma

    aioclient_mock.get(jma.OBSERVATION_INDEX, json=JMA_OBSERVATIONS)
    aioclient_mock.get(jma.FORECAST_INDEX, json=JMA_FORECASTS)
    aioclient_mock.get(BASE_TILE, content=png_bytes((0, 0, 255, 255)))
    aioclient_mock.get(RADAR_TILE, content=png_bytes((255, 0, 0, 255)))
    return aioclient_mock


async def _setup(hass: HomeAssistant, **kwargs) -> MockConfigEntry:
    """Add and set up a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Rain Cloud Radar",
        data=CONFIG_DATA,
        unique_id="test",
        **kwargs,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_unload(hass: HomeAssistant, mock_jma) -> None:
    """The entry sets up both entities and unloads cleanly."""
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(CAMERA_ENTITY) is not None
    assert hass.states.get(IMAGE_ENTITY) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_the_provider_is_down(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A failing provider leaves the entry in the retry state."""
    from custom_components.raincloudradar.sources import jma

    aioclient_mock.get(jma.OBSERVATION_INDEX, status=503)
    aioclient_mock.get(jma.FORECAST_INDEX, status=503)

    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG_DATA, unique_id="test")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_camera_returns_the_rendered_picture(
    hass: HomeAssistant, mock_jma
) -> None:
    """The camera hands out a PNG of the configured size."""
    from homeassistant.components.camera import async_get_image

    await _setup(hass)

    image = await async_get_image(hass, CAMERA_ENTITY)

    assert image.content_type == "image/png"
    from PIL import Image

    picture = Image.open(io.BytesIO(image.content))
    assert picture.format == "PNG"
    assert picture.size == (CONFIG_DATA["width"], CONFIG_DATA["height"])


async def test_image_entity_serves_the_same_picture(
    hass: HomeAssistant, mock_jma
) -> None:
    """Both entities share one render instead of fetching tiles twice."""
    from homeassistant.components.camera import async_get_image

    await _setup(hass)

    camera_image = await async_get_image(hass, CAMERA_ENTITY)
    tiles_after_first = mock_jma.call_count

    entity = hass.data["image"].get_entity(IMAGE_ENTITY)
    image_bytes = await entity.async_image()

    assert image_bytes == camera_image.content
    assert mock_jma.call_count == tiles_after_first


async def test_image_timestamp_follows_the_frame(hass: HomeAssistant, mock_jma) -> None:
    """The image entity publishes the frame time so the frontend refreshes."""
    await _setup(hass)

    entity = hass.data["image"].get_entity(IMAGE_ENTITY)

    assert entity.image_last_updated == datetime(2025, 1, 1, 0, 5, tzinfo=UTC)


async def test_state_attributes_describe_the_frame(
    hass: HomeAssistant, mock_jma
) -> None:
    """The attributes tell which frame is on screen."""
    await _setup(hass)

    state = hass.states.get(CAMERA_ENTITY)

    assert state is not None
    assert state.attributes[ATTR_FRAME_TIME] == "2025-01-01T00:05:00+00:00"
    assert state.attributes[ATTR_IS_FORECAST] is False
    assert state.attributes[ATTR_ZOOM] == 9


async def test_forecast_offset_picks_a_nowcast_frame(
    hass: HomeAssistant, mock_jma
) -> None:
    """With an offset the entity shows a forecast frame."""
    await _setup(hass, options={CONF_FORECAST_OFFSET: 30})

    state = hass.states.get(CAMERA_ENTITY)

    assert state is not None
    assert state.attributes[ATTR_IS_FORECAST] is True


async def test_changing_options_reloads_the_entry(
    hass: HomeAssistant, mock_jma
) -> None:
    """New options are applied by reloading the entry."""
    entry = await _setup(hass)

    hass.config_entries.async_update_entry(entry, options={CONF_ZOOM: 6})
    await hass.async_block_till_done()

    state = hass.states.get(CAMERA_ENTITY)
    assert state is not None
    assert state.attributes[ATTR_ZOOM] == 6


async def test_frames_are_polled_on_the_configured_interval(
    hass: HomeAssistant, mock_jma
) -> None:
    """The coordinator refreshes the index without rendering again."""
    from custom_components.raincloudradar.sources import jma

    await _setup(hass)
    calls_before = sum(
        1 for call in mock_jma.mock_calls if str(call[1]) == jma.OBSERVATION_INDEX
    )

    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=6))
    await hass.async_block_till_done()

    calls_after = sum(
        1 for call in mock_jma.mock_calls if str(call[1]) == jma.OBSERVATION_INDEX
    )
    assert calls_after > calls_before


async def test_deep_zoom_magnifies_the_radar_layer(
    hass: HomeAssistant, mock_jma
) -> None:
    """The map keeps zooming past the provider, the radar layer is blown up."""
    await _setup(hass, options={CONF_ZOOM: 14})

    state = hass.states.get(CAMERA_ENTITY)

    assert state is not None
    # The base map (GSI pale) serves zoom 14, the JMA nowcast stops at 10.
    assert state.attributes[ATTR_ZOOM] == 14
    assert state.attributes[ATTR_RADAR_ZOOM] == 10


async def test_zoom_is_limited_by_the_base_map(hass: HomeAssistant, mock_jma) -> None:
    """A base map that stops at zoom 14 caps the picture there."""
    await _setup(hass, options={CONF_ZOOM: 16, CONF_BASE_MAP: "gsi_blank"})

    state = hass.states.get(CAMERA_ENTITY)

    assert state is not None
    assert state.attributes[ATTR_ZOOM] == 14


async def test_config_resolves_base_map_defaults(hass: HomeAssistant) -> None:
    """Without an explicit choice the provider decides the base map."""
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG_DATA, unique_id="test")
    entry.add_to_hass(hass)

    config = RadarConfig.from_entry(entry)

    assert config.base_map == "gsi_pale"
    assert config.base_map_url is not None
    assert "地理院" in config.base_map_attribution


async def test_config_without_a_base_map(hass: HomeAssistant) -> None:
    """The base map can be switched off entirely."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=CONFIG_DATA, options={CONF_BASE_MAP: "none"}, unique_id="x"
    )
    entry.add_to_hass(hass)

    config = RadarConfig.from_entry(entry)

    assert config.base_map_url is None
    assert config.base_map_attribution == ""


async def test_diagnostics(hass: HomeAssistant, mock_jma) -> None:
    """Diagnostics describe the entry without leaking the location."""
    from custom_components.raincloudradar.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _setup(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["data"]["location"] == "**REDACTED**"
    assert diagnostics["source"]["effective_zoom"] == 9
    assert diagnostics["frames"]["count"] == 4
    assert diagnostics["frames"]["selected"]["is_forecast"] is False
