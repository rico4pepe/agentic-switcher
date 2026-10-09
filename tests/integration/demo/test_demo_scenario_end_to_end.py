"""End-to-end integration tests for demo scenarios."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from switcher.demo.scenarios import DemoScenarioName, reset_demo_scenario


client = TestClient(app)


def test_normal_scenario_execution_through_api():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "NORMAL"},
    )
    assert response.status_code == 200
    assert response.json()["scenario"] == "NORMAL"


def test_vendor_a_unavailable_scenario_affects_routing():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "VENDOR_A_UNAVAILABLE"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["vendor_a_available"] is False
    assert data["vendor_b_available"] is True


def test_policy_denied_scenario_configuration():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "POLICY_DENIED"},
    )
    assert response.status_code == 200
    data = response.json()
    assert Decimal(data["account_balance_override"]) == Decimal("0")


def test_timeout_scenario_configuration():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "TIMEOUT"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["vendor_simulation"]["vendor_a_timeout"] is True


def test_planner_a_a_unavailable_scenario_configuration():
    reset_demo_scenario()
    response = client.post(
        "/api/demo/scenarios",
        json={"scenario": "PLANNER_A_A_UNAVAILABLE"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["vendor_a_available"] is False
