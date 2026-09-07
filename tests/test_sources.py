"""Tests for the radar providers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.raincloudradar.sources import (
    RadarSource,
    SourceError,
    create_source,
)
from custom_components.raincloudradar.sources.base import RadarFrame
from custom_components.raincloudradar.sources.jma import parse_target_times
from custom_components.raincloudradar.sources.rainviewer import parse_weather_maps

from .fixtures import JMA_FORECASTS, JMA_OBSERVATIONS, RAINVIEWER_INDEX


def test_create_source_rejects_unknown_keys() -> None:
    """An unknown provider is reported instead of silently ignored."""
    with pytest.raises(SourceError):
        create_source("nope")


def test_jma_observations_are_not_forecasts() -> None:
    """Entries whose base and valid time match are observations."""
    frames = parse_target_times(JMA_OBSERVATIONS)

    assert len(frames) == 2
    assert [frame.is_forecast for frame in frames] == [False, False]
    assert frames[0].valid_time == datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    assert "/20250101000000/none/20250101000000/surf/hrpns/" in frames[0].url_template
    assert frames[0].url_template.endswith("/{z}/{x}/{y}.png")


def test_jma_forecasts_use_the_immed_path() -> None:
    """Frames ahead of their base time are served from the forecast path."""
    frames = parse_target_times(JMA_FORECASTS)

    assert [frame.is_forecast for frame in frames] == [True, True]
    assert "/20250101000500/immed/20250101001000/surf/hrpns/" in frames[0].url_template


def test_jma_skips_unusable_entries() -> None:
    """Malformed or unrelated entries do not break the update."""
    frames = parse_target_times(
        [
            {"basetime": "not-a-time", "validtime": "20250101000000"},
            {"basetime": "20250101000000"},
            {
                "basetime": "20250101000000",
                "validtime": "20250101000000",
                "elements": ["liden"],
            },
            "garbage",
            {
                "basetime": "20250101000000",
                "validtime": "20250101000000",
                "elements": ["hrpns"],
            },
        ]
    )

    assert len(frames) == 1


def test_jma_rejects_a_payload_that_is_not_a_list() -> None:
    """A completely unexpected document raises."""
    with pytest.raises(SourceError):
        parse_target_times({"unexpected": True})


def test_rainviewer_builds_tile_templates() -> None:
    """Past and nowcast entries both become frames."""
    frames = parse_weather_maps(RAINVIEWER_INDEX, color_scheme=4)

    assert len(frames) == 3
    assert [frame.is_forecast for frame in frames] == [False, False, True]
    assert frames[0].url_template == (
        "https://tilecache.rainviewer.com/v2/radar/1735689000/256"
        "/{z}/{x}/{y}/4/1_1.png"
    )
    assert frames[-1].valid_time == datetime(2025, 1, 1, 0, 10, tzinfo=UTC)


def test_rainviewer_requires_radar_data() -> None:
    """A payload without radar data is an error."""
    with pytest.raises(SourceError):
        parse_weather_maps({"host": "https://example.com"})


def test_rainviewer_falls_back_to_the_default_host() -> None:
    """A payload without a host still yields usable URLs."""
    frames = parse_weather_maps(
        {"radar": {"past": [{"time": 1735689000, "path": "/v2/radar/1"}]}}
    )
    assert frames[0].url_template.startswith("https://tilecache.rainviewer.com/")


def _frame(minute: int, *, forecast: bool = False) -> RadarFrame:
    """Build a frame at ``minute`` past midnight."""
    moment = datetime(2025, 1, 1, 0, minute, tzinfo=UTC)
    return RadarFrame(
        valid_time=moment,
        base_time=moment,
        is_forecast=forecast,
        url_template=f"https://example.com/{minute}/{{z}}/{{x}}/{{y}}.png",
    )


def test_select_frame_prefers_the_latest_observation() -> None:
    """Without an offset the newest observation wins over the nowcast."""
    frames = [_frame(0), _frame(5), _frame(10, forecast=True)]
    now = datetime(2025, 1, 1, 0, 6, tzinfo=UTC)

    selected = RadarSource.select_frame(frames, now)

    assert selected is not None
    assert selected.valid_time.minute == 5


def test_select_frame_honours_the_offset() -> None:
    """With an offset the frame closest to that moment is used."""
    frames = [
        _frame(0),
        _frame(5),
        _frame(10, forecast=True),
        _frame(35, forecast=True),
    ]
    now = datetime(2025, 1, 1, 0, 5, tzinfo=UTC)

    selected = RadarSource.select_frame(frames, now, offset_minutes=30)

    assert selected is not None
    assert selected.valid_time.minute == 35


def test_select_frame_without_frames() -> None:
    """An empty list simply has no frame to show."""
    assert RadarSource.select_frame([], datetime.now(UTC)) is None


def test_zoom_is_clamped_to_what_the_provider_serves() -> None:
    """The JMA nowcast only publishes zoom 4 to 10."""
    source = create_source("jma")
    assert source.clamp_zoom(12) == 10
    assert source.clamp_zoom(2) == 4
    assert source.clamp_zoom(8) == 8


async def test_jma_source_merges_observations_and_forecasts(
    aioclient_mock, hass
) -> None:
    """Both indexes are combined into one ordered list of frames."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.raincloudradar.sources import jma

    aioclient_mock.get(jma.OBSERVATION_INDEX, json=JMA_OBSERVATIONS)
    aioclient_mock.get(jma.FORECAST_INDEX, json=JMA_FORECASTS)

    frames = await create_source("jma").async_get_frames(async_get_clientsession(hass))

    assert [frame.is_forecast for frame in frames] == [False, False, True, True]
    assert frames == sorted(frames, key=lambda frame: frame.valid_time)


async def test_jma_source_survives_a_missing_forecast_index(
    aioclient_mock, hass
) -> None:
    """Observations alone are enough to render a picture."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.raincloudradar.sources import jma

    aioclient_mock.get(jma.OBSERVATION_INDEX, json=JMA_OBSERVATIONS)
    aioclient_mock.get(jma.FORECAST_INDEX, status=500)

    frames = await create_source("jma").async_get_frames(async_get_clientsession(hass))

    assert len(frames) == 2


async def test_jma_source_reports_an_unreachable_index(aioclient_mock, hass) -> None:
    """A failing observation index is surfaced as a source error."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.raincloudradar.sources import jma

    aioclient_mock.get(jma.OBSERVATION_INDEX, status=503)
    aioclient_mock.get(jma.FORECAST_INDEX, status=503)

    with pytest.raises(SourceError):
        await create_source("jma").async_get_frames(async_get_clientsession(hass))


async def test_rainviewer_source_fetches_the_index(aioclient_mock, hass) -> None:
    """The RainViewer index is turned into frames."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.raincloudradar.sources import rainviewer

    aioclient_mock.get(rainviewer.INDEX_URL, json=RAINVIEWER_INDEX)

    source = create_source("rainviewer", color_scheme=2)
    frames = await source.async_get_frames(async_get_clientsession(hass))

    assert len(frames) == 3
    assert "/2/1_1.png" in frames[0].url_template
