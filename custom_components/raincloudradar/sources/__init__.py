"""Radar tile providers supported by the Rain Cloud Radar integration."""

from __future__ import annotations

from ..const import SOURCE_JMA, SOURCE_RAINVIEWER
from .base import RadarFrame, RadarSource, SourceError
from .jma import JmaNowcastSource
from .rainviewer import RainViewerSource

SOURCE_CLASSES: dict[str, type[RadarSource]] = {
    SOURCE_JMA: JmaNowcastSource,
    SOURCE_RAINVIEWER: RainViewerSource,
}


def create_source(key: str, **kwargs: object) -> RadarSource:
    """Instantiate the radar source registered under ``key``."""
    try:
        source_class = SOURCE_CLASSES[key]
    except KeyError:
        raise SourceError(f"Unknown radar source: {key}") from None
    return source_class(**kwargs)  # type: ignore[arg-type]


__all__ = [
    "SOURCE_CLASSES",
    "JmaNowcastSource",
    "RadarFrame",
    "RadarSource",
    "RainViewerSource",
    "SourceError",
    "create_source",
]
