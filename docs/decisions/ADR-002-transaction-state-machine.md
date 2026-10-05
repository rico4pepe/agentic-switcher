# ADR-002: Explicit Transaction State Machine

**Status:** Implemented

## Decision

Transactions use an explicit state machine rather than unconstrained state assignment.

## States

`CREATED`, `VALIDATING`, `VALIDATED`, `SUBMITTED`, `SUCCESS`, `FAILED`, `UNKNOWN`, `INVESTIGATING`, and `STATUS_RESOLVED`.

## Implemented transitions

```text
CREATED → VALIDATING
VALIDATING → VALIDATED | FAILED
VALIDATED → SUBMITTED | FAILED
SUBMITTED → SUCCESS | FAILED | UNKNOWN
UNKNOWN → INVESTIGATING
INVESTIGATING → STATUS_RESOLVED
STATUS_RESOLVED → SUCCESS | FAILED
```

`SUCCESS` and `FAILED` are terminal. The `Transaction.transition_to()` method delegates validation to the state machine, so application services use transitions rather than directly setting lifecycle state. This makes permitted outcomes and ambiguous outcomes explicit and testable.
