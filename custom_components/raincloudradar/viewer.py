"""An interactive viewer page that can be embedded with an iframe card.

Home Assistant's picture cards show a still image; they cannot be panned or
pinched.  This module serves a small page that can, by re-rendering the radar
picture whenever the gesture ends, so zooming in really does show more detail.

The endpoints are unauthenticated - an ``<iframe>`` cannot send Home
Assistant's bearer token - and are instead guarded by a per entry token, the
same approach Home Assistant uses for webhooks.  They only exist while the
viewer is switched on in the options.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    VIEWER_MAX_SIZE,
    VIEWER_MIN_SIZE,
    VIEWER_URL,
)

_LOGGER = logging.getLogger(__name__)

DATA_VIEWS_REGISTERED = "views_registered"


@callback
def async_register_views(hass: HomeAssistant) -> None:
    """Register the viewer endpoints once per Home Assistant instance."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_VIEWS_REGISTERED):
        return
    hass.http.register_view(RadarViewerPageView(hass))
    hass.http.register_view(RadarViewerImageView(hass))
    domain_data[DATA_VIEWS_REGISTERED] = True


def viewer_path(token: str) -> str:
    """Return the path of the viewer page for ``token``."""
    return VIEWER_URL.format(token=token)


def _find_entry(hass: HomeAssistant, token: str) -> ConfigEntry | None:
    """Return the loaded entry whose viewer token matches, if any."""
    if not token:
        return None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        config = entry.runtime_data.config
        if not config.viewer_enabled or not config.viewer_token:
            continue
        if hmac.compare_digest(config.viewer_token, token):
            return entry
    return None


def _int_param(query: Any, name: str, default: int, low: int, high: int) -> int:
    """Read one integer query parameter, clamped into ``low``..``high``."""
    try:
        value = int(float(query.get(name, default)))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _float_param(
    query: Any, name: str, default: float, low: float, high: float
) -> float:
    """Read one float query parameter, clamped into ``low``..``high``."""
    try:
        value = float(query.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


class RadarViewerPageView(HomeAssistantView):
    """Serve the HTML page that hosts the interactive radar picture."""

    url = VIEWER_URL
    name = "api:raincloudradar:viewer"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the view."""
        self.hass = hass

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Return the viewer page."""
        entry = _find_entry(self.hass, token)
        if entry is None:
            # Do not tell an unknown caller whether the token merely expired.
            raise web.HTTPNotFound

        config = entry.runtime_data.config
        source = entry.runtime_data.coordinator.source
        page_config = {
            "token": token,
            "latitude": config.latitude,
            "longitude": config.longitude,
            "zoom": config.effective_zoom(source),
            "minZoom": config.clamp_zoom(source, -99),
            "maxZoom": config.clamp_zoom(source, 99),
            "maxPixels": VIEWER_MAX_SIZE,
            "refreshSeconds": max(60, config.update_interval * 60),
        }
        page = PAGE_TEMPLATE.replace(
            "__CONFIG__", json.dumps(page_config).replace("</", "<\\/")
        ).replace("__TITLE__", _escape(config.name))
        return web.Response(
            text=page,
            content_type="text/html",
            charset="utf-8",
            headers={"Cache-Control": "no-store"},
        )


class RadarViewerImageView(HomeAssistantView):
    """Render the radar picture for an arbitrary window of the map."""

    url = VIEWER_URL + "/image"
    name = "api:raincloudradar:viewer:image"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the view."""
        self.hass = hass

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Return a freshly rendered PNG."""
        entry = _find_entry(self.hass, token)
        if entry is None:
            raise web.HTTPNotFound

        data = entry.runtime_data
        source = data.coordinator.source
        query = request.query
        image = await data.provider.async_render_window(
            latitude=_float_param(query, "lat", data.config.latitude, -85.0, 85.0),
            longitude=_float_param(query, "lon", data.config.longitude, -180.0, 180.0),
            zoom=data.config.clamp_zoom(
                source, _int_param(query, "z", data.config.zoom, -99, 99)
            ),
            width=_int_param(query, "w", 640, VIEWER_MIN_SIZE, VIEWER_MAX_SIZE),
            height=_int_param(query, "h", 480, VIEWER_MIN_SIZE, VIEWER_MAX_SIZE),
        )
        if image is None:
            raise web.HTTPServiceUnavailable

        return web.Response(
            body=image,
            content_type="image/png",
            headers={"Cache-Control": "no-store"},
        )


def _escape(text: str) -> str:
    """Escape the few characters that matter inside the page title."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light dark; }
  html, body { margin: 0; height: 100%; overflow: hidden; background: #e9ebee; }
  #stage {
    position: absolute; inset: 0; overflow: hidden;
    touch-action: none; user-select: none; -webkit-user-select: none;
  }
  #picture {
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; transform-origin: center center;
    -webkit-user-drag: none; pointer-events: none;
  }
  #controls {
    position: absolute; right: 10px; bottom: 10px;
    display: flex; flex-direction: column; gap: 6px; z-index: 2;
  }
  #controls button {
    width: 40px; height: 40px; border: 0; border-radius: 8px;
    background: rgba(0, 0, 0, .55); color: #fff;
    font-size: 20px; line-height: 1; cursor: pointer;
  }
  #controls button:active { background: rgba(0, 0, 0, .8); }
  #badge {
    position: absolute; left: 10px; bottom: 10px; z-index: 2;
    padding: 4px 8px; border-radius: 6px;
    background: rgba(0, 0, 0, .55); color: #fff;
    font: 12px/1.4 system-ui, sans-serif;
  }
  #badge.busy::after { content: " ..."; }
</style>
</head>
<body>
<div id="stage">
  <img id="picture" alt="__TITLE__">
  <div id="badge">z<span id="zoomLabel"></span></div>
  <div id="controls">
    <button id="zoomIn" title="拡大">+</button>
    <button id="zoomOut" title="縮小">-</button>
    <button id="reset" title="初期位置">&#8635;</button>
  </div>
</div>
<script>
(function () {
  "use strict";
  var CONFIG = __CONFIG__;
  var TILE = 256;

  var stage = document.getElementById("stage");
  var picture = document.getElementById("picture");
  var zoomLabel = document.getElementById("zoomLabel");
  var badge = document.getElementById("badge");

  var home = { lat: CONFIG.latitude, lon: CONFIG.longitude, z: CONFIG.zoom };
  var view = { lat: home.lat, lon: home.lon, z: home.z };
  var gesture = { tx: 0, ty: 0, scale: 1 };
  var pointers = new Map();
  var start = null;
  var pending = 0;

  function worldPixel(lat, lon, z) {
    var span = TILE * Math.pow(2, z);
    var sin = Math.sin(Math.max(-85.05, Math.min(85.05, lat)) * Math.PI / 180);
    return {
      x: (lon + 180) / 360 * span,
      y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * span
    };
  }

  function pixelLatLon(x, y, z) {
    var span = TILE * Math.pow(2, z);
    var n = Math.PI - 2 * Math.PI * y / span;
    return {
      lat: 180 / Math.PI * Math.atan(Math.sinh(n)),
      lon: x / span * 360 - 180
    };
  }

  function clampZoom(z) {
    return Math.max(CONFIG.minZoom, Math.min(CONFIG.maxZoom, z));
  }

  function applyGesture() {
    picture.style.transform = "translate(" + gesture.tx + "px," + gesture.ty +
      "px) scale(" + gesture.scale + ")";
  }

  function resetGesture() {
    gesture = { tx: 0, ty: 0, scale: 1 };
    applyGesture();
  }

  /* Ask for the picture that matches the current view and swap it in. */
  function refresh() {
    var width = Math.max(1, Math.round(stage.clientWidth));
    var height = Math.max(1, Math.round(stage.clientHeight));
    /* On a dense display render twice the pixels one zoom level deeper: the
       map keeps its apparent scale but gains detail, like retina tiles. */
    var dense = window.devicePixelRatio >= 1.5 &&
                width * 2 <= CONFIG.maxPixels && height * 2 <= CONFIG.maxPixels &&
                view.z + 1 <= CONFIG.maxZoom;
    var factor = dense ? 2 : 1;
    var url = CONFIG.token + "/image" +
      "?lat=" + view.lat.toFixed(6) +
      "&lon=" + view.lon.toFixed(6) +
      "&z=" + (view.z + (dense ? 1 : 0)) +
      "&w=" + Math.min(CONFIG.maxPixels, width * factor) +
      "&h=" + Math.min(CONFIG.maxPixels, height * factor) +
      "&_=" + Date.now();

    var token = ++pending;
    badge.classList.add("busy");
    var next = new Image();
    next.onload = function () {
      if (token !== pending) { return; }
      picture.src = next.src;
      resetGesture();
      badge.classList.remove("busy");
    };
    next.onerror = function () {
      if (token === pending) { badge.classList.remove("busy"); }
    };
    next.src = url;
    zoomLabel.textContent = view.z;
  }

  /* Turn the pan/pinch that just happened into a new centre and zoom. */
  function commit() {
    var scale = gesture.scale;
    var centre = worldPixel(view.lat, view.lon, view.z);
    var moved = pixelLatLon(
      centre.x - gesture.tx / scale,
      centre.y - gesture.ty / scale,
      view.z
    );
    var zoom = clampZoom(Math.round(view.z + Math.log(scale) / Math.LN2));
    var unchanged = zoom === view.z &&
      Math.abs(gesture.tx) < 1 && Math.abs(gesture.ty) < 1 &&
      Math.abs(scale - 1) < 0.01;
    view.lat = moved.lat;
    view.lon = moved.lon;
    view.z = zoom;
    if (unchanged) { resetGesture(); } else { refresh(); }
  }

  function centreOf(list) {
    var x = 0, y = 0;
    list.forEach(function (p) { x += p.x; y += p.y; });
    return { x: x / list.length, y: y / list.length };
  }

  function spreadOf(list) {
    if (list.length < 2) { return 0; }
    return Math.hypot(list[0].x - list[1].x, list[0].y - list[1].y);
  }

  function beginGesture() {
    var list = Array.from(pointers.values());
    start = {
      centre: centreOf(list),
      spread: spreadOf(list),
      tx: gesture.tx,
      ty: gesture.ty,
      scale: gesture.scale
    };
  }

  stage.addEventListener("pointerdown", function (event) {
    /* Capturing the pointer would send the follow up click to the stage
       instead of the button that was pressed, so leave the controls alone. */
    if (event.target.closest && event.target.closest("#controls")) { return; }
    try { stage.setPointerCapture(event.pointerId); } catch (err) { /* ignore */ }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    beginGesture();
  });

  stage.addEventListener("pointermove", function (event) {
    if (!pointers.has(event.pointerId) || start === null) { return; }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    var list = Array.from(pointers.values());
    var centre = centreOf(list);
    var scale = 1;
    if (list.length > 1 && start.spread > 0) {
      scale = spreadOf(list) / start.spread;
    }
    gesture.scale = start.scale * scale;
    gesture.tx = start.tx * scale + (centre.x - start.centre.x);
    gesture.ty = start.ty * scale + (centre.y - start.centre.y);
    applyGesture();
  });

  function endPointer(event) {
    if (!pointers.delete(event.pointerId)) { return; }
    if (pointers.size > 0) { beginGesture(); return; }
    start = null;
    commit();
  }

  stage.addEventListener("pointerup", endPointer);
  stage.addEventListener("pointercancel", endPointer);

  stage.addEventListener("wheel", function (event) {
    event.preventDefault();
    step(event.deltaY < 0 ? 1 : -1);
  }, { passive: false });

  stage.addEventListener("dblclick", function () { step(1); });

  function step(delta) {
    var zoom = clampZoom(view.z + delta);
    if (zoom === view.z) { return; }
    view.z = zoom;
    refresh();
  }

  document.getElementById("zoomIn")
    .addEventListener("click", function () { step(1); });
  document.getElementById("zoomOut")
    .addEventListener("click", function () { step(-1); });
  document.getElementById("reset").addEventListener("click", function () {
    view = { lat: home.lat, lon: home.lon, z: home.z };
    refresh();
  });

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(refresh, 300);
  });

  /* Pick up new radar frames while the page stays open. */
  setInterval(function () {
    if (pointers.size === 0 && !document.hidden) { refresh(); }
  }, CONFIG.refreshSeconds * 1000);

  refresh();
})();
</script>
</body>
</html>
"""
