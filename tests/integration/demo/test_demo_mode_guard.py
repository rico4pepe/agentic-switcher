"""Test demo mode boundary behavior."""

from fastapi.testclient import TestClient

from apps.api.app import config
from apps.api.app.main import app
from switcher.demo.scenarios import DemoScenarioName, get_demo_scenario, reset_demo_scenario


def test_demo_endpoints_unavailable_when_demo_mode_disabled(monkeypatch):
    reset_demo_scenario()
    monkeypatch.setattr(config.settings, "demo_mode_enabled", False)
    client = TestClient(app)
    response = client.get("/api/demo/scenarios")
    assert response.status_code == 404
    response = client.post("/api/demo/scenarios", json={"scenario": "NORMAL"})
    assert response.status_code == 404
    # When disabled, scenario state remains unchanged
    assert get_demo_scenario() == DemoScenarioName.NORMAL


def test_demo_endpoints_available_when_demo_mode_enabled(monkeypatch):
    reset_demo_scenario()
    monkeypatch.setattr(config.settings, "demo_mode_enabled", True)
    client = TestClient(app)
    response = client.get("/api/demo/scenarios")
    assert response.status_code == 200
