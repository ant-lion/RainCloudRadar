"""Shared fixtures for the Rain Cloud Radar tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# The integration lives in ``custom_components`` at the root of the repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True, scope="session")
def use_threaded_dns_resolver():
    """Keep aiodns out of the way.

    Recent pycares releases start a background thread as soon as a channel is
    created, which the Home Assistant test harness reports as a leaked thread.
    The tests never resolve a real host, so the threaded resolver will do.
    """
    from aiohttp.resolver import ThreadedResolver

    with patch("aiohttp.connector.DefaultResolver", ThreadedResolver):
        yield


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom integration available to every test."""
    return
