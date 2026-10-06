"""Tests for transaction state transitions."""

import pytest

from apps.api.app.domain.state_machine import (
    InvalidTransactionTransition,
    TransactionStateMachine,
)
from apps.api.app.domain.transaction import TransactionState


def test_created_can_transition_to_validating():
    result = TransactionStateMachine.transition(
        TransactionState.CREATED,
        TransactionState.VALIDATING,
    )

    assert result == TransactionState.VALIDATING


def test_submitted_can_transition_to_unknown():
    result = TransactionStateMachine.transition(
        TransactionState.SUBMITTED,
        TransactionState.UNKNOWN,
    )

    assert result == TransactionState.UNKNOWN


def test_validated_can_transition_to_submitting():
    assert TransactionStateMachine.transition(
        TransactionState.VALIDATED,
        TransactionState.SUBMITTING,
    ) == TransactionState.SUBMITTING


def test_submitting_can_transition_to_submitted():
    assert TransactionStateMachine.transition(
        TransactionState.SUBMITTING,
        TransactionState.SUBMITTED,
    ) == TransactionState.SUBMITTED


def test_submitting_can_transition_to_failed():
    assert TransactionStateMachine.transition(
        TransactionState.SUBMITTING,
        TransactionState.FAILED,
    ) == TransactionState.FAILED


def test_submitting_can_transition_to_unknown():
    assert TransactionStateMachine.transition(
        TransactionState.SUBMITTING,
        TransactionState.UNKNOWN,
    ) == TransactionState.UNKNOWN


def test_unknown_must_go_through_investigation():
    with pytest.raises(InvalidTransactionTransition):
        TransactionStateMachine.transition(
            TransactionState.UNKNOWN,
            TransactionState.SUCCESS,
        )


def test_investigation_can_resolve_to_success():
    result = TransactionStateMachine.transition(
        TransactionState.STATUS_RESOLVED,
        TransactionState.SUCCESS,
    )

    assert result == TransactionState.SUCCESS


def test_investigation_can_resolve_to_failed():
    result = TransactionStateMachine.transition(
        TransactionState.STATUS_RESOLVED,
        TransactionState.FAILED,
    )

    assert result == TransactionState.FAILED


def test_unknown_can_be_preserved_after_unresolved_investigation():
    assert TransactionStateMachine.transition(
        TransactionState.INVESTIGATING,
        TransactionState.UNKNOWN,
    ) == TransactionState.UNKNOWN


def test_state_machine_rejects_validated_to_submitted():
    with pytest.raises(InvalidTransactionTransition):
        TransactionStateMachine.transition(
            TransactionState.VALIDATED,
            TransactionState.SUBMITTED,
        )


def test_success_is_terminal():
    with pytest.raises(InvalidTransactionTransition):
        TransactionStateMachine.transition(
            TransactionState.SUCCESS,
            TransactionState.VALIDATING,
        )


def test_failed_is_terminal():
    with pytest.raises(InvalidTransactionTransition):
        TransactionStateMachine.transition(
            TransactionState.FAILED,
            TransactionState.SUBMITTED,
        )