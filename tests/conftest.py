"""Shared test fixtures ensuring demo scenario state isolation."""

import pytest

from switcher.demo.scenarios import reset_demo_scenario
from switcher.routing import reset_vendor_availability


@pytest.fixture(autouse=True)
def _reset_demo_scenario_state():
    """Reset demo scenario state before and after every test."""
    reset_demo_scenario()
    reset_vendor_availability()
    yield
    reset_demo_scenario()
    reset_vendor_availability()
