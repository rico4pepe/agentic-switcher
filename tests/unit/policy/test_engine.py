"""Tests for deterministic prepaid policy evaluation."""

from decimal import Decimal

import pytest

from policy.account_context import AccountContext, AccountType, DemoAccountContextProvider
from policy.engine import PolicyAction, PolicyEngine


@pytest.mark.parametrize(
    ("balance", "amount", "expected_action", "expected_reason"),
    [
        ("10000.00", "5000.00", PolicyAction.ALLOW, "Sufficient balance"),
        ("2000.00", "5000.00", PolicyAction.DENY, "Insufficient balance"),
        ("5000.00", "5000.00", PolicyAction.ALLOW, "Sufficient balance"),
    ],
)
def test_prepaid_balance_policy_is_deterministic(
    balance: str,
    amount: str,
    expected_action: PolicyAction,
    expected_reason: str,
):
    account = AccountContext(
        beneficiary="08030000001",
        account_type=AccountType.PREPAID,
        balance=Decimal(balance),
    )
    engine = PolicyEngine(DemoAccountContextProvider((account,)))

    decision = engine.evaluate("08030000001", Decimal(amount))

    assert decision.action == expected_action
    assert decision.reason == expected_reason


def test_unknown_account_fails_closed():
    decision = PolicyEngine().evaluate("08030000000", Decimal("5000.00"))

    assert decision.action == PolicyAction.DENY
    assert decision.reason == "Account context not found"
