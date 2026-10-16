# ADR-002: Explicit Transaction State Machine

**Status:** Implemented

## Decision

Transactions use an explicit state machine rather than unconstrained state assignment.

## States

`CREATED`, `VALIDATING`, `VALIDATED`, `SUBMITTING`, `SUBMITTED`, `SUCCESS`, `FAILED`, `UNKNOWN`, `INVESTIGATING`, and `STATUS_RESOLVED`.

`SUBMITTING` is the durable pre-submission boundary: it is recorded before the vendor is contacted, so an uncertain submission can be recognised and reconciled rather than lost.

## Implemented transitions

```text
CREATED → VALIDATING
VALIDATING → VALIDATED | FAILED
VALIDATED → SUBMITTING | FAILED
SUBMITTING → SUBMITTED | FAILED | UNKNOWN
SUBMITTED → SUCCESS | FAILED | UNKNOWN
UNKNOWN → INVESTIGATING
INVESTIGATING → STATUS_RESOLVED | UNKNOWN
STATUS_RESOLVED → SUCCESS | FAILED
```

`SUCCESS` and `FAILED` are terminal.

`UNKNOWN → INVESTIGATING` models investigation of an ambiguous outcome; `INVESTIGATING → UNKNOWN` models an investigation that itself returns no new information.

## Enforcement

`TransactionStateMachine` (`apps/api/app/domain/state_machine.py`) defines this canonical allowed-transition set, and `Transaction.transition_to()` validates against it. The authoritative persistence path (`switcher/transactions/persistence_service.py`) applies state changes through compare-and-set (CAS) updates that fix both the expected current state and the target state, so only one writer can advance a transaction from a given state; the transitions it performs are drawn from the set above. This makes permitted outcomes and ambiguous outcomes explicit and testable.
