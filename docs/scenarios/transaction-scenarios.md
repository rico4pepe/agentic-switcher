# Transaction Scenarios

These scenarios describe expected system behavior and boundaries. Only the successful Vendor A MTN airtime path and its validation failure path are currently implemented. All other scenarios below are planned.

| Scenario | Intended behavior | Status |
| --- | --- | --- |
| Successful airtime transaction | Validate, submit, persist `SUCCESS`, and retain vendor reference. | Implemented for deterministic Vendor A MTN airtime. |
| Different vendor workflow | Follow that capability's ordered required/optional workflow. | Planned. |
| Missing customer | Reject or fail validation without execution. | Planned. |
| Unsupported product | Report no applicable capability; do not execute. | Planned. |
| Prepaid insufficient balance | Record deterministic execution failure. | Planned. |
| Postpaid credit limit exceeded | Record deterministic execution failure. | Planned. |
| Vendor timeout → `UNKNOWN` | Preserve ambiguity rather than mark `FAILED`. | State transition implemented; timeout handling is planned. |
| `UNKNOWN` → `SUCCESS` | Investigate with a status query and resolve success. | Planned. |
| `UNKNOWN` → `FAILED` | Investigate with a status query and resolve failure. | Planned. |
| Duplicate prevention | Prevent duplicate financial/product delivery during retries and ambiguity. | Planned. |

## Future retry-safety scenario — not implemented

```text
UNKNOWN → status query → FAILED → deterministic retry policy → ask user before retry
```

A confirmed failure is not by itself permission to retry. Any future retry must be allowed by deterministic policy and explicitly confirmed by the user.
