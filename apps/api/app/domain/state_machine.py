"""Transaction state transition rules."""

from apps.api.app.domain.transaction import TransactionState


class InvalidTransactionTransition(ValueError):
    """Raised when a transaction state transition is not allowed."""


class TransactionStateMachine:
    """Validate and apply transaction state transitions."""

    _TRANSITIONS: dict[TransactionState, set[TransactionState]] = {
        TransactionState.CREATED: {
            TransactionState.VALIDATING,
        },
        TransactionState.VALIDATING: {
            TransactionState.VALIDATED,
            TransactionState.FAILED,
        },
        TransactionState.VALIDATED: {
            TransactionState.SUBMITTED,
            TransactionState.FAILED,
        },
        TransactionState.SUBMITTED: {
            TransactionState.SUCCESS,
            TransactionState.FAILED,
            TransactionState.UNKNOWN,
        },
        TransactionState.UNKNOWN: {
            TransactionState.INVESTIGATING,
        },
        TransactionState.INVESTIGATING: {
            TransactionState.STATUS_RESOLVED,
        },
        TransactionState.STATUS_RESOLVED: {
            TransactionState.SUCCESS,
            TransactionState.FAILED,
        },
        TransactionState.SUCCESS: set(),
        TransactionState.FAILED: set(),
    }

    @classmethod
    def can_transition(
        cls,
        current: TransactionState,
        target: TransactionState,
    ) -> bool:
        """Return whether a state transition is allowed."""
        return target in cls._TRANSITIONS.get(current, set())

    @classmethod
    def transition(
        cls,
        current: TransactionState,
        target: TransactionState,
    ) -> TransactionState:
        """Validate and return the target state."""
        if not cls.can_transition(current, target):
            raise InvalidTransactionTransition(
                f"Invalid transaction transition: "
                f"{current.value} -> {target.value}"
            )

        return target