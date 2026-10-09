"""Minimal server-side demo scenario control API.

The browser may only select a bounded scenario name. It may not supply vendor
codes, adapters, credentials, statuses, balances, raw HTTP, or any other
arbitrary state. Selecting a scenario arms configuration only; it never
executes a transaction.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.config import settings
from switcher.demo.scenarios import (
    DemoScenarioName,
    get_demo_scenario_controller,
    get_demo_scenario_config,
    reset_demo_scenario,
    set_demo_scenario,
)


def _require_demo_mode_enabled() -> None:
    if not settings.demo_mode_enabled:
        raise HTTPException(status_code=404, detail="Demo endpoints are disabled")


router = APIRouter(prefix="/api/demo", tags=["demo"], dependencies=[Depends(_require_demo_mode_enabled)])


class SetScenarioRequest(BaseModel):
    """Bounded request body accepting only a scenario identifier."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenario: str = Field(min_length=1, max_length=64)


class ScenarioResponse(BaseModel):
    """The backend conditions armed by a scenario."""

    model_config = ConfigDict(from_attributes=True)

    scenario: DemoScenarioName
    vendor_a_available: bool
    vendor_b_available: bool
    account_balance_override: str | None = None
    vendor_simulation: dict[str, object] = Field(default_factory=dict)
    description: str


def _serialize(config) -> ScenarioResponse:
    return ScenarioResponse(
        scenario=config.scenario,
        vendor_a_available=config.vendor_a_available,
        vendor_b_available=config.vendor_b_available,
        account_balance_override=(
            None
            if config.account_balance_override is None
            else str(config.account_balance_override)
        ),
        vendor_simulation=config.vendor_simulation.model_dump(),
        description=config.description,
    )


@router.get("/scenarios")
def list_scenarios() -> dict[str, object]:
    """Return the active scenario and the bounded set of available scenarios."""
    return {
        "current": _serialize(get_demo_scenario_config()),
        "available": [
            _serialize(config)
            for config in get_demo_scenario_controller().available()
        ],
    }


@router.post("/scenarios")
def select_scenario(request: SetScenarioRequest) -> ScenarioResponse:
    """Arm a demo scenario by name. Unknown names are rejected."""
    try:
        scenario = DemoScenarioName(request.scenario)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario name: {request.scenario}",
        ) from error
    return _serialize(set_demo_scenario(scenario))


@router.post("/scenarios/reset")
def reset_scenario() -> ScenarioResponse:
    """Restore normal demo conditions."""
    return _serialize(reset_demo_scenario())
