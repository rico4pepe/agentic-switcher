"""Deterministic development/demo planner provider for the LLMProvider boundary.

This implementation satisfies the existing application-level ``LLMProvider``
contract consumed by ``ExecutionPlanPlanner``. It deterministically parses the
prompt produced by the planner boundary and returns a valid ``ExecutionPlan``
without any model invocation. It is intended for local development and demo
planning only; the Bedrock provider remains the production planning
implementation.
"""

import ast
import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from agent.execution_plan import ExecutionPlan, PlanStep
from agent.llm_provider import StructuredOutput


class DeterministicPlannerProviderError(RuntimeError):
    """Raised when the deterministic provider cannot produce a valid plan."""


_FIELD_LINE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")

_CAPABILITY_LINE = re.compile(
    r"^\s*-\s*vendor=(?P<vendor>[^,]+)"
    r",\s*service=[^,]+,"
    r"\s*product=[^,]+,"
    r"\s*network=[^,]+,"
    r"\s*required_planner_steps=\[(?P<steps>[^\]]*)\]"
    r",\s*supported="
)

_PLAN_STEP_ORDER = {step: index for index, step in enumerate(PlanStep)}


@dataclass(frozen=True)
class _ParsedCapability:
    """One canonical capability summary parsed from the planner prompt."""

    vendor_code: str
    steps: tuple[str, ...]


class DeterministicPlannerProvider:
    """Produce a deterministic ExecutionPlan for the planner prompt."""

    def __init__(self, *, proposed_vendor_code: str = "vendor_a") -> None:
        self._proposed_vendor_code = proposed_vendor_code

    def generate_structured(
        self,
        prompt: str,
        output_model: type[StructuredOutput],
    ) -> StructuredOutput:
        """Return the deterministic ExecutionPlan matching the planner prompt."""
        if output_model is not ExecutionPlan:
            raise DeterministicPlannerProviderError(
                "Deterministic planner provider only supports ExecutionPlan output"
            )

        capabilities = self._parse_capabilities(prompt)
        steps = self._required_planner_steps(capabilities)
        fields = self._parse_fields(prompt)

        try:
            return ExecutionPlan(
                intent=fields.get("intent", ""),
                service_type=fields.get("service_type", ""),
                product_type=fields.get("product_type", ""),
                network=self._optional_string(fields.get("network")),
                beneficiary=fields.get("beneficiary", ""),
                amount=fields.get("amount", ""),
                candidate_vendor=self._propose_candidate_vendor(capabilities),
                steps=steps,
            )
        except ValidationError as error:
            raise DeterministicPlannerProviderError(
                "Planner prompt is malformed or missing required fields"
            ) from error

    @staticmethod
    def _parse_fields(prompt: str) -> dict[str, str]:
        """Parse line-oriented ``key=value`` request fields from the prompt."""
        fields: dict[str, str] = {}
        for line in prompt.splitlines():
            match = _FIELD_LINE.match(line)
            if match is not None:
                fields[match.group("key")] = match.group("value").strip()
        return fields

    @staticmethod
    def _parse_capabilities(prompt: str) -> tuple[_ParsedCapability, ...]:
        """Parse the canonical capability summaries from the prompt."""
        capabilities = []
        for line in prompt.splitlines():
            match = _CAPABILITY_LINE.match(line)
            if match is None:
                continue
            steps = DeterministicPlannerProvider._parse_step_list(
                match.group("steps")
            )
            capabilities.append(
                _ParsedCapability(
                    vendor_code=match.group("vendor").strip(),
                    steps=steps,
                )
            )
        return tuple(capabilities)

    @staticmethod
    def _parse_step_list(raw_steps: str) -> tuple[str, ...]:
        """Parse the ``required_planner_steps=[...]`` list from a capability."""
        if not raw_steps.strip():
            return ()
        try:
            steps = ast.literal_eval(f"[{raw_steps}]")
        except (ValueError, SyntaxError):
            return ()
        if not isinstance(steps, list) or not all(
            isinstance(step, str) for step in steps
        ):
            return ()
        return tuple(steps)

    @staticmethod
    def _required_planner_steps(
        capabilities: Sequence[_ParsedCapability],
    ) -> tuple[PlanStep, ...]:
        """Return the deterministic union of valid required planner steps."""
        steps: set[PlanStep] = set()
        for capability in capabilities:
            for value in capability.steps:
                try:
                    steps.add(PlanStep(value))
                except ValueError:
                    continue
        if not steps:
            raise DeterministicPlannerProviderError(
                "Planner prompt does not list any valid required planner steps"
            )
        return tuple(sorted(steps, key=lambda step: _PLAN_STEP_ORDER[step]))

    def _propose_candidate_vendor(
        self,
        capabilities: Sequence[_ParsedCapability],
    ) -> str | None:
        """Propose the configured vendor only when it is a supplied capability."""
        vendor_codes = {
            capability.vendor_code
            for capability in capabilities
        }
        if self._proposed_vendor_code in vendor_codes:
            return self._proposed_vendor_code
        return None

    @staticmethod
    def _optional_string(value: str | None) -> str | None:
        if value in (None, "", "None"):
            return None
        return value