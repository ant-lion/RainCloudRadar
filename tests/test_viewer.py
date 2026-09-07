"""Tests for the interactive viewer endpoints."""

from __future__ import annotations

import io
import re

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.raincloudradar.const import (
    ATTR_VIEWER_URL,
    CONF_ENABLE_VIEWER,
    CONF_VIEWER_TOKEN,
    DOMAIN,
    VIEWER_MAX_SIZE,
)
from custom_components.raincloudradar.viewer import _float_param, _int_param

from .fixtures import CONFIG_DATA, JMA_FORECASTS, JMA_OBSERVATIONS, png_bytes

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


async def _setup(hass: HomeAssistant, *, viewer: bool = True) -> MockConfigEntry:
    """Set up an entry with or without the viewer."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Rain Cloud Radar",
        data=CONFIG_DATA,
        options={CONF_ENABLE_VIEWER: viewer},
        unique_id="test",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_int_param_clamps_and_falls_back() -> None:
    """Query parameters never leave the allowed range."""
    assert _int_param({"w": "640"}, "w", 320, 128, 1600) == 640
    assert _int_param({"w": "99999"}, "w", 320, 128, 1600) == 1600
    assert _int_param({"w": "-5"}, "w", 320, 128, 1600) == 128
    assert _int_param({"w": "nonsense"}, "w", 320, 128, 1600) == 320
    assert _int_param({}, "w", 320, 128, 1600) == 320


def test_float_param_clamps_and_falls_back() -> None:
    """The same holds for the coordinates."""
    assert _float_param({"lat": "35.5"}, "lat", 0.0, -85.0, 85.0) == 35.5
    assert _float_param({"lat": "120"}, "lat", 0.0, -85.0, 85.0) == 85.0
    assert _float_param({"lat": "x"}, "lat", 1.5, -85.0, 85.0) == 1.5


async def test_a_token_is_generated_and_kept(hass: HomeAssistant, mock_jma) -> None:
    """The entry gets a viewer token, which survives a reload."""
    entry = await _setup(hass)

    token = entry.data[CONF_VIEWER_TOKEN]
    assert len(token) == 32

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_VIEWER_TOKEN] == token


async def test_the_entities_publish_the_viewer_address(
    hass: HomeAssistant, mock_jma
) -> None:
    """The address to put into the iframe card is readable from the state."""
    entry = await _setup(hass)

    state = hass.states.get("camera.rain_cloud_radar_radar")

    assert state is not None
    assert state.attributes[ATTR_VIEWER_URL] == (
        f"/api/raincloudradar/{entry.data[CONF_VIEWER_TOKEN]}"
    )


async def test_no_viewer_address_when_disabled(hass: HomeAssistant, mock_jma) -> None:
    """A switched off viewer is not advertised."""
    await _setup(hass, viewer=False)

    state = hass.states.get("camera.rain_cloud_radar_radar")

    assert state is not None
    assert ATTR_VIEWER_URL not in state.attributes


async def test_page_is_served_for_the_right_token(
    hass: HomeAssistant, mock_jma, hass_client_no_auth
) -> None:
    """The page carries the settings the script needs."""
    entry = await _setup(hass)
    client = await hass_client_no_auth()

    response = await client.get(f"/api/raincloudradar/{entry.data[CONF_VIEWER_TOKEN]}")

    assert response.status == 200
    assert response.content_type == "text/html"
    body = await response.text()
    assert '"zoom": 9' in body
    assert '"maxZoom": 16' in body
    assert entry.data[CONF_VIEWER_TOKEN] in body


async def test_page_hides_behind_the_token(
    hass: HomeAssistant, mock_jma, hass_client_no_auth
) -> None:
    """A wrong token is indistinguishable from a missing page."""
    await _setup(hass)
    client = await hass_client_no_auth()

    response = await client.get("/api/raincloudradar/" + "0" * 32)

    assert response.status == 404


async def test_no_endpoints_while_the_viewer_is_off(
    hass: HomeAssistant, mock_jma, hass_client_no_auth
) -> None:
    """Nothing is served when the option is not switched on."""
    entry = await _setup(hass, viewer=False)
    client = await hass_client_no_auth()

    response = await client.get(f"/api/raincloudradar/{entry.data[CONF_VIEWER_TOKEN]}")

    assert response.status == 404


async def test_image_endpoint_renders_the_requested_window(
    hass: HomeAssistant, mock_jma, hass_client_no_auth
) -> None:
    """The picture matches the requested size and position."""
    from PIL import Image

    entry = await _setup(hass)
    client = await hass_client_no_auth()
    token = entry.data[CONF_VIEWER_TOKEN]

    response = await client.get(
        f"/api/raincloudradar/{token}/image?lat=34.7&lon=135.5&z=13&w=320&h=240"
    )

    assert response.status == 200
    assert response.content_type == "image/png"
    picture = Image.open(io.BytesIO(await response.read()))
    assert picture.size == (320, 240)


async def test_image_endpoint_clamps_absurd_requests(
    hass: HomeAssistant, mock_jma, hass_client_no_auth
) -> None:
    """Out of range values are clamped instead of rejected."""
    from PIL import Image

    entry = await _setup(hass)
    client = await hass_client_no_auth()
    token = entry.data[CONF_VIEWER_TOKEN]

    response = await client.get(
        f"/api/raincloudradar/{token}/image?lat=999&lon=999&z=99&w=1&h=999999"
    )

    assert response.status == 200
    picture = Image.open(io.BytesIO(await response.read()))
    assert picture.size[1] == VIEWER_MAX_SIZE


async def test_image_endpoint_needs_the_token(
    hass: HomeAssistant, mock_jma, hass_client_no_auth
) -> None:
    """The renderer is not reachable without the token either."""
    await _setup(hass)
    client = await hass_client_no_auth()

    response = await client.get("/api/raincloudradar/" + "0" * 32 + "/image")

    assert response.status == 404
