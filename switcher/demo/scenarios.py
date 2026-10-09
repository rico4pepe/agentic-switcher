"""Bounded server-side demo scenario control.

Scenarios configure existing dependencies (vendor availability, account
context, vendor simulation conditions) rather than faking transaction
outcomes. The scenario name is the only control a caller may supply. No
scenario endpoint may set a vendor code, transaction status, balance, adapter,
credential, or raw HTTP behavior directly.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DemoScenarioName(StrEnum):
    """The bounded set of demonstrable scenarios."""

    NORMAL = "NORMAL"
    VENDOR_A_UNAVAILABLE = "VENDOR_A_UNAVAILABLE"
    POLICY_DENIED = "POLICY_DENIED"
    TIMEOUT = "TIMEOUT"
    PLANNER_A_A_UNAVAILABLE = "PLANNER_A_A_UNAVAILABLE"


class VendorSimulationConfig(BaseModel):
    """Condition the vendor simulator should reproduce during execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vendor_a_timeout: bool = False
    vendor_b_timeout: bool = False


class DemoScenarioConfig(BaseModel):
    """The backend conditions armed by a demo scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: DemoScenarioName
    vendor_a_available: bool = True
    vendor_b_available: bool = True
    account_balance_override: Decimal | None = None
    vendor_simulation: VendorSimulationConfig = Field(
        default_factory=VendorSimulationConfig
    )
    description: str


_SCENARIO_CONFIGS: dict[DemoScenarioName, DemoScenarioConfig] = {
    DemoScenarioName.NORMAL: DemoScenarioConfig(
        scenario=DemoScenarioName.NORMAL,
        description="Vendor A available and preferred; normal account balance.",
    ),
    DemoScenarioName.VENDOR_A_UNAVAILABLE: DemoScenarioConfig(
        scenario=DemoScenarioName.VENDOR_A_UNAVAILABLE,
        vendor_a_available=False,
        vendor_b_available=True,
        description="Vendor A unavailable; the Switcher selects Vendor B.",
    ),
    DemoScenarioName.POLICY_DENIED: DemoScenarioConfig(
        scenario=DemoScenarioName.POLICY_DENIED,
        vendor_a_available=False,
        vendor_b_available=True,
        account_balance_override=Decimal("0"),
        description="Insufficient balance; Policy denies before vendor submission.",
    ),
    DemoScenarioName.TIMEOUT: DemoScenarioConfig(
        scenario=DemoScenarioName.TIMEOUT,
        vendor_simulation=VendorSimulationConfig(vendor_a_timeout=True),
        description="Vendor A submission times out; transaction remains UNKNOWN.",
    ),
    DemoScenarioName.PLANNER_A_A_UNAVAILABLE: DemoScenarioConfig(
        scenario=DemoScenarioName.PLANNER_A_A_UNAVAILABLE,
        vendor_a_available=False,
        vendor_b_available=True,
        description=(
            "Planner may propose Vendor A, but A is unavailable; "
            "the Switcher independently selects Vendor B."
        ),
    ),
}


class DemoScenarioController:
    """In-memory holder of the active demo scenario configuration."""

    def __init__(self) -> None:
        self._scenario = DemoScenarioName.NORMAL

    @property
    def scenario(self) -> DemoScenarioName:
        return self._scenario

    @property
    def config(self) -> DemoScenarioConfig:
        return _SCENARIO_CONFIGS[self._scenario]

    def set(self, scenario: DemoScenarioName) -> DemoScenarioConfig:
        if not isinstance(scenario, DemoScenarioName):
            raise ValueError(f"Unknown demo scenario: {scenario!r}")
        self._scenario = scenario
        return self.config

    def reset(self) -> DemoScenarioConfig:
        return self.set(DemoScenarioName.NORMAL)

    def available(self) -> tuple[DemoScenarioConfig, ...]:
        return tuple(_SCENARIO_CONFIGS[name] for name in DemoScenarioName)


_controller = DemoScenarioController()


def get_demo_scenario_controller() -> DemoScenarioController:
    return _controller


def get_demo_scenario() -> DemoScenarioName:
    return _controller.scenario


def get_demo_scenario_config() -> DemoScenarioConfig:
    return _controller.config


def set_demo_scenario(scenario: DemoScenarioName) -> DemoScenarioConfig:
    return _controller.set(scenario)


def reset_demo_scenario() -> DemoScenarioConfig:
    return _controller.reset()
