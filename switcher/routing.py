"""Deterministic vendor routing for demo execution.

This is intentionally small and explicit: it supports a runtime availability
state and a deterministic preference order without turning the registry into a
ranking engine.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent.execution_plan import ExecutionPlan, validate_execution_plan_against_capability
from capabilities.domain import Capability, CapabilityOperation

DEFAULT_VENDOR_PRIORITY = {
    "vendor_a": 1,
    "vendor_b": 2,
}

_RUNTIME_AVAILABILITY: dict[str, bool] = {
    "vendor_a": True,
    "vendor_b": True,
}


def set_vendor_availability(vendor_code: str, available: bool) -> None:
    """Update the demo runtime availability state for a deterministic vendor."""
    _RUNTIME_AVAILABILITY[vendor_code] = available


def get_vendor_availability(vendor_code: str) -> bool:
    """Return whether a vendor is currently available for execution."""
    return bool(_RUNTIME_AVAILABILITY.get(vendor_code, True))


def reset_vendor_availability() -> None:
    """Reset the demo runtime availability to the default available state."""
    for vendor_code in DEFAULT_VENDOR_PRIORITY:
        _RUNTIME_AVAILABILITY[vendor_code] = True


def _compatible_executable_capabilities(
    plan: ExecutionPlan,
    capabilities: Sequence[Capability],
) -> tuple[Capability, ...]:
    compatibility_plan = plan.model_copy(update={"candidate_vendor": None})
    compatible = []
    for capability in capabilities:
        if CapabilityOperation.EXECUTE_TRANSACTION not in capability.supported_operations:
            continue
        try:
            validate_execution_plan_against_capability(
                compatibility_plan,
                capability,
            )
        except ValueError:
            continue
        if not get_vendor_availability(capability.vendor_code):
            continue
        compatible.append(capability)
    return tuple(compatible)


def resolve_execution_vendor_code(
    plan: ExecutionPlan,
    capabilities: Sequence[Capability],
) -> str:
    """Choose the deterministic available vendor without allowing first-capability fallback."""
    eligible = _compatible_executable_capabilities(plan, capabilities)
    if not eligible:
        raise ValueError("No eligible vendor is available for the requested transaction")

    return min(
        (capability.vendor_code for capability in eligible),
        key=lambda vendor_code: DEFAULT_VENDOR_PRIORITY.get(vendor_code, 99),
    )


def determine_execution_vendor_code(
    plan: ExecutionPlan,
    capabilities: Sequence[Capability],
) -> str:
    """Backward-compatible alias for deterministic execution vendor selection."""
    return resolve_execution_vendor_code(plan, capabilities)


def select_execution_vendor_code(
    plan: ExecutionPlan,
    capabilities: Sequence[Capability],
) -> str:
    """Alias used by the orchestrator boundary to resolve the selected vendor code."""
    return resolve_execution_vendor_code(plan, capabilities)
