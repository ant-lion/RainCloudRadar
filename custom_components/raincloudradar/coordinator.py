"""Frame polling and picture rendering for Rain Cloud Radar."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import BASE_TILE_TTL, DOMAIN, RADAR_TILE_TTL, USER_AGENT
from .models import RadarConfig
from .renderer import MapView, RenderRequest, async_render, format_caption
from .sources import RadarFrame, RadarSource, SourceError
from .tiles import TileCache, TileFetcher

_LOGGER = logging.getLogger(__name__)

#: How many ad hoc viewer renders to keep around.
WINDOW_CACHE_SIZE = 12


class RainCloudRadarCoordinator(DataUpdateCoordinator[list[RadarFrame]]):
    """Poll the radar provider for the list of frames it currently offers.

    Only the small JSON index is polled here; the tiles themselves are fetched
    lazily by :class:`RadarImageProvider` when an entity asks for a picture.
    """

    def __init__(
        self, hass: HomeAssistant, config: RadarConfig, source: RadarSource
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config.name})",
            update_interval=timedelta(minutes=max(1, config.update_interval)),
        )
        self.config = config
        self.source = source

    async def _async_update_data(self) -> list[RadarFrame]:
        """Fetch the available frames from the provider."""
        session = async_get_clientsession(self.hass)
        try:
            return await self.source.async_get_frames(session)
        except SourceError as err:
            raise UpdateFailed(str(err)) from err

    @property
    def current_frame(self) -> RadarFrame | None:
        """Return the frame matching the configured time offset."""
        if not self.data:
            return None
        return self.source.select_frame(
            self.data, dt_util.utcnow(), self.config.forecast_offset
        )


class RadarImageProvider:
    """Render the radar picture, reusing the result across entities.

    The camera and image entities of one config entry ask for the very same
    picture, so it is rendered once per frame and then handed out from a cache.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: RainCloudRadarCoordinator,
    ) -> None:
        """Initialise the provider."""
        self._hass = hass
        self._coordinator = coordinator
        self._lock = asyncio.Lock()
        self._cache_key: str | None = None
        self._image: bytes | None = None
        self._windows: dict[tuple[str, str, MapView], bytes] = {}
        self._fetcher = TileFetcher(
            async_get_clientsession(hass),
            user_agent=USER_AGENT,
            cache=TileCache(),
        )

    @property
    def config(self) -> RadarConfig:
        """Return the configuration of the entry."""
        return self._coordinator.config

    def _build_request(
        self, frame: RadarFrame, view: MapView, radar_zoom: int
    ) -> RenderRequest:
        """Describe the picture of ``frame`` for the given map window."""
        config = self.config
        source = self._coordinator.source

        caption = None
        if config.show_caption:
            caption = format_caption(
                config.name,
                dt_util.as_local(frame.valid_time),
                frame.is_forecast,
            )

        attribution = source.attribution
        if base_credit := config.base_map_attribution:
            attribution = f"{attribution} / {base_credit}"

        return RenderRequest(
            view=view,
            radar_url_template=frame.url_template,
            radar_zoom_out=view.zoom - radar_zoom,
            base_map_url_template=config.base_map_url,
            opacity=config.opacity,
            show_marker=config.show_marker,
            caption=caption,
            attribution=attribution,
            base_tile_ttl=BASE_TILE_TTL,
            radar_tile_ttl=RADAR_TILE_TTL,
        )

    def _configured_view(self) -> tuple[MapView, int]:
        """Return the map window of the config entry and its radar zoom."""
        config = self.config
        source = self._coordinator.source
        view = MapView(
            latitude=config.latitude,
            longitude=config.longitude,
            zoom=config.effective_zoom(source),
            width=config.width,
            height=config.height,
        )
        return view, config.radar_zoom(source)

    async def async_render_window(
        self,
        *,
        latitude: float,
        longitude: float,
        zoom: int,
        width: int,
        height: int,
    ) -> bytes | None:
        """Render an arbitrary window of the map, for the interactive viewer.

        Results are kept for a short while so panning back and forth does not
        re-render, and rendering is serialised to bound the work one client can
        ask for.
        """
        frame = self._coordinator.current_frame
        if frame is None:
            return None

        view = MapView(
            latitude=latitude,
            longitude=longitude,
            zoom=zoom,
            width=width,
            height=height,
        )
        radar_zoom = min(zoom, self._coordinator.source.max_zoom)
        key = (frame.key, self._config_fingerprint(), view)

        if (cached := self._windows.get(key)) is not None:
            return cached

        async with self._lock:
            if (cached := self._windows.get(key)) is not None:
                return cached
            image = await self._async_compose(frame, view, radar_zoom)
            if image is None:
                return None
            self._windows[key] = image
            while len(self._windows) > WINDOW_CACHE_SIZE:
                self._windows.pop(next(iter(self._windows)))
            return image

    async def _async_compose(
        self, frame: RadarFrame, view: MapView, radar_zoom: int
    ) -> bytes | None:
        """Fetch the tiles and compose one picture, swallowing failures."""
        try:
            return await async_render(
                self._fetcher,
                self._build_request(frame, view, radar_zoom),
                self._hass.async_add_executor_job,
            )
        except Exception:  # never let a broken render take an entity down
            _LOGGER.exception("Failed to render the radar picture")
            return None

    async def async_image(self) -> bytes | None:
        """Return the current picture, rendering it when the frame changed."""
        frame = self._coordinator.current_frame
        if frame is None:
            return self._image

        cache_key = f"{frame.key}|{self._config_fingerprint()}"
        if cache_key == self._cache_key and self._image is not None:
            return self._image

        async with self._lock:
            # A concurrent caller may have rendered the picture in the meantime.
            if cache_key == self._cache_key and self._image is not None:
                return self._image
            view, radar_zoom = self._configured_view()
            image = await self._async_compose(frame, view, radar_zoom)
            if image is None:
                return self._image

            self._image = image
            self._cache_key = cache_key
            return image

    def _config_fingerprint(self) -> str:
        """Return a key that changes whenever the rendering options change."""
        config = self.config
        return "|".join(
            str(part)
            for part in (
                config.latitude,
                config.longitude,
                config.zoom,
                config.width,
                config.height,
                config.base_map,
                config.custom_base_map_url,
                config.opacity,
                config.show_marker,
                config.show_caption,
            )
        )

    def clear(self) -> None:
        """Drop the cached picture and tiles."""
        self._cache_key = None
        self._image = None
        self._windows.clear()
        self._fetcher.cache.clear()
