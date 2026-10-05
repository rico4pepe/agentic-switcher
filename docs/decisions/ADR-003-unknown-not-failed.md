# ADR-003: UNKNOWN Is Not FAILED

**Status:** Implemented state model; investigation execution is planned

## Decision

A vendor timeout or ambiguous response does not prove transaction failure. A submitted transaction may transition to `UNKNOWN`, not automatically to `FAILED`.

## State-model behavior

```text
SUBMITTED → UNKNOWN → INVESTIGATING → STATUS_RESOLVED → SUCCESS | FAILED
```

Investigation is intended to perform a vendor status query. A timeout must never be treated as automatic failure, and an `UNKNOWN` transaction must never be blindly retried because duplicate execution may result.

## Future behavior — not implemented

If investigation confirms `FAILED`, a retry may be considered only when deterministic retry policy permits it. The user should then be asked for confirmation before retrying. No retry policy, investigation service, status-query workflow, or user-confirmation flow is implemented today.
