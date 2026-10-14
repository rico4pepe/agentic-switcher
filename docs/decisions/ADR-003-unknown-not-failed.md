# ADR-003: UNKNOWN Is Not FAILED

**Status:** Implemented (state model + deterministic investigation); retry policy and conversational recovery planned

## Decision

A vendor timeout or ambiguous response does not prove transaction failure. A submitted transaction may transition to `UNKNOWN`, not automatically to `FAILED`.

## State-model behavior

```text
SUBMITTED → UNKNOWN → INVESTIGATING → STATUS_RESOLVED → SUCCESS | FAILED
```

Investigation is implemented at the deterministic engine/MCP level: the
`TransactionInvestigator` and the read-only `get_transaction_status` MCP tool
query the vendor and reconcile an `UNKNOWN`/`SUBMITTING`/`SUBMITTED` transaction
through `INVESTIGATING` → `STATUS_RESOLVED` → `SUCCESS | FAILED`. It remains a
manual/engine-level capability and is not triggered from the conversational
flow. A timeout must never be treated as automatic failure, and an `UNKNOWN`
transaction must never be blindly retried because duplicate execution may result.

## Future behavior — not implemented

If investigation confirms `FAILED`, a retry may be considered only when
deterministic retry policy permits it. The user would then be asked for
confirmation before retrying. No retry policy or user-confirmation retry flow is
implemented today, and `UNKNOWN` is still never automatically retried.
