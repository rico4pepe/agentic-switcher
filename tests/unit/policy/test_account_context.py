"""Tests for the minimal account context model and configured lookup."""

from decimal import Decimal

from policy.account_context import AccountContext, AccountType, DemoAccountContextProvider


def test_account_context_accepts_required_account_facts():
    context = AccountContext(
        beneficiary="08030000001",
        account_type=AccountType.PREPAID,
        balance=Decimal("10000.00"),
    )

    assert context.beneficiary == "08030000001"
    assert context.account_type == AccountType.PREPAID
    assert context.balance == Decimal("10000.00")


def test_default_demo_account_context_uses_configured_demo_values():
    context = DemoAccountContextProvider().get("08030000001")

    assert context is not None
    assert context.account_type == AccountType.PREPAID
    assert context.balance == Decimal("10000")


def test_demo_account_lookup_does_not_return_another_beneficiarys_context():
    provider = DemoAccountContextProvider()

    assert provider.get("08030000000") is None
