"""Tests for demo scenario API endpoints."""

from fastapi.testclient import TestClient

from apps.api.app.main import app
from switcher.demo.scenarios import DemoScenarioName, reset_demo_scenario


client = TestClient(app)


def test_get_scenarios_returns_current_and_available():
    reset_demo_scenario()
    response = client.get("/api/demo/scenarios")
    assert response.status_code == 200
    data = response.json()
    assert "current" in data
    assert "available" in data
    assert data["current"]["scenario"] == DemoScenarioName.NORMAL.value


def test_post_scenarios_sets_valid_scenario():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "VENDOR_A_UNAVAILABLE"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scenario"] == "VENDOR_A_UNAVAILABLE"
    assert data["vendor_a_available"] is False
    assert data["vendor_b_available"] is True


def test_post_scenarios_rejects_unknown_scenario():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "UNKNOWN_BAD_SCENARIO"},
    )
    assert response.status_code == 400


def test_post_scenarios_rejects_arbitrary_fields():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "NORMAL", "vendor_code": "vendor_b"},
    )
    assert response.status_code == 422  # pydantic validation error for extra fields


def test_reset_scenario():
    reset_demo_scenario()
    client.post("/api/demo/scenarios", json={"scenario": "TIMEOUT"})
    response = client.post("/api/demo/scenarios/reset")
    assert response.status_code == 200
    data = response.json()
    assert data["scenario"] == "NORMAL"
