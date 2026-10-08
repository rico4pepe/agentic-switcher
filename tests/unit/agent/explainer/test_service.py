"""Unit tests for the deterministic AgentResult explainer."""

import ast
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest

from agent.explainer.service import TransactionExplainer
from agent.runtime.service import AgentResult


def result(
    *,
    status: Literal[
        "created",
        "validating",
        "validated",
        "submitting",
        "submitted",
        "success",
        "failed",
        "unknown",
        "investigating",
        "status_resolved",
        "denied",
    ] = "success",
    network: str | None = "MTN",
    vendor_code: str | None = "vendor_a",
    action: Literal["allow", "deny"] | None = "allow",
    reason: str | None = None,
    message: str = "Transaction completed successfully",
) -> AgentResult:
    return AgentResult(
        transaction_id=UUID("8e4cb8cf-79da-49ab-aa35-865d1105b45e"),
        status=status,
        service_type="airtime",
        product_type="airtime",
        network=network,
        beneficiary="08030000001",
        amount=Decimal("5000.00"),
        vendor_code=vendor_code,
        vendor_reference=None,
        action=action,
        reason=reason,
        message=message,
    )


def test_success_explains_amount_beneficiary_and_actual_vendor():
    explanation = TransactionExplainer().explain(result())

    assert explanation == (
        "Your ₦5,000 MTN airtime purchase for 08030000001 "
        "was completed successfully through Vendor A."
    )


def test_success_formats_fractional_amount_without_rounding_it():
    fractional = result()
    fractional.amount = Decimal("1250.75")

    explanation = TransactionExplainer().explain(fractional)

    assert "₦1,250.75" in explanation


def test_policy_denial_uses_reason_without_inventing_balance():
    denied = result(
        status="denied",
        action="deny",
        reason="Insufficient balance",
        message="Insufficient balance",
    )

    explanation = TransactionExplainer().explain(denied)

    assert "couldn't complete" in explanation
    assert "Insufficient balance" in explanation
    assert "₦2,000" not in explanation
    assert "available balance" not in explanation


def test_failure_uses_the_actual_result_message():
    failed = result(
        status="failed",
        action=None,
        reason="Validation failed",
        message="Customer validation failed",
    )

    explanation = TransactionExplainer().explain(failed)

    assert "could not be completed" in explanation
    assert "Customer validation failed" in explanation


def test_unknown_remains_uncertain_even_if_message_contains_terminal_claim():
    unknown = result(
        status="unknown",
        action=None,
        message="Transaction failed",
    )

    explanation = TransactionExplainer().explain(unknown)

    assert explanation == (
        "The transaction could not be confirmed yet. "
        "Its status is still uncertain."
    )
    assert "success" not in explanation.lower()
    assert "failed" not in explanation.lower()
    assert "completed" not in explanation.lower()
    assert "retrying" not in explanation.lower()


def test_unknown_preserves_nonterminal_message_without_investigating():
    unknown = result(
        status="unknown",
        action=None,
        message="Vendor response timed out; confirmation is pending.",
    )

    explanation = TransactionExplainer().explain(unknown)

    assert "status is still uncertain" in explanation
    assert "Vendor response timed out; confirmation is pending." in explanation
    assert "retry" not in explanation.lower()


def test_vendor_b_explanation_uses_the_vendor_in_agent_result():
    explanation = TransactionExplainer().explain(
        result(vendor_code="vendor_b")
    )

    assert "through Vendor B" in explanation
    assert "Vendor A" not in explanation


def test_missing_optional_fields_do_not_cause_crashes():
    minimal = result(
        network=None,
        vendor_code=None,
        action=None,
        reason=None,
    )

    explanation = TransactionExplainer().explain(minimal)

    assert "₦5,000 airtime purchase for 08030000001" in explanation
    assert "through Vendor" not in explanation


def test_success_preserves_only_investigation_facts_present_in_message():
    explained = TransactionExplainer().explain(
        result(message="Confirmed successful after investigation.")
    )

    assert "completed successfully through Vendor A" in explained
    assert "Confirmed successful after investigation." in explained
    assert "timed out" not in explained


def test_explainer_does_not_mutate_agent_result():
    structured_result = result()
    before = structured_result.model_dump()

    TransactionExplainer().explain(structured_result)

    assert structured_result.model_dump() == before


@pytest.mark.parametrize(
    "module_path",
    [
        Path(__file__).parents[4] / "agent" / "explainer" / "service.py",
        Path(__file__).parents[4] / "agent" / "explainer" / "templates.py",
    ],
)
def test_explainer_modules_have_no_execution_layer_imports(module_path: Path):
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_roots = {
        "apps",
        "capabilities",
        "mcp",
        "policy",
        "requests",
        "sqlalchemy",
        "switcher",
        "vendors",
    }

    assert not {
        module
        for module in imported_modules
        if module.split(".", maxsplit=1)[0] in forbidden_roots
    }
