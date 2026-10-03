"""Tests for transaction domain behavior."""

from decimal import Decimal

import pytest

from apps.api.app.domain.state_machine import InvalidTransactionTransition
from apps.api.app.domain.transaction import Transaction, TransactionState


def make_transaction() -> Transaction:
    """Create an in-memory transaction for testing."""
    return Transaction(
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000.00"),
    )


def test_transaction_starts_in_created_state():
    transaction = make_transaction()

    assert transaction.state == TransactionState.CREATED


def test_transaction_can_transition_to_validating():
    transaction = make_transaction()

    transaction.transition_to(TransactionState.VALIDATING)

    assert transaction.state == TransactionState.VALIDATING


def test_transaction_rejects_invalid_transition():
    transaction = make_transaction()

    with pytest.raises(InvalidTransactionTransition):
        transaction.transition_to(TransactionState.SUCCESS)


def test_transaction_cannot_skip_investigation_after_unknown():
    transaction = make_transaction()

    transaction.transition_to(TransactionState.VALIDATING)
    transaction.transition_to(TransactionState.VALIDATED)
    transaction.transition_to(TransactionState.SUBMITTED)
    transaction.transition_to(TransactionState.UNKNOWN)

    with pytest.raises(InvalidTransactionTransition):
        transaction.transition_to(TransactionState.SUCCESS)


def test_transaction_can_resolve_unknown_transaction():
    transaction = make_transaction()

    transaction.transition_to(TransactionState.VALIDATING)
    transaction.transition_to(TransactionState.VALIDATED)
    transaction.transition_to(TransactionState.SUBMITTED)
    transaction.transition_to(TransactionState.UNKNOWN)
    transaction.transition_to(TransactionState.INVESTIGATING)
    transaction.transition_to(TransactionState.STATUS_RESOLVED)
    transaction.transition_to(TransactionState.SUCCESS)

    assert transaction.state == TransactionState.SUCCESS