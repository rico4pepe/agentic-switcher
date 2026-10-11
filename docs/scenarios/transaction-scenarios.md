# Transaction Scenarios

These scenarios describe expected system behavior and boundaries. Status below is
reconciled against the current implementation and tests; where behavior exists only
at the deterministic state-machine/persistence layer rather than as a complete
user-facing flow, that distinction is stated explicitly.

Deterministic execution is implemented for MTN airtime through Vendor A and Vendor B,
with Switcher routing between them, a demo prepaid insufficient-balance denial, and a
deterministic recovery path for uncertain (`UNKNOWN`) outcomes. The conversational
path (`POST /api/chat`) currently surfaces a single authoritative result per request;
it does not yet drive a stateful recovery conversation.

| Scenario                       | Intended behavior                                                             | Status                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Successful airtime transaction | Validate, submit, persist`SUCCESS`, and retain vendor reference.            | Implemented for deterministic Vendor A and Vendor B MTN airtime.                                                                                                                                                                                                                                                                          |
| Different vendor workflow      | Follow that capability's ordered required/optional workflow.                  | Partially implemented. Deterministic multi-vendor routing exists, but only MTN airtime capabilities are seeded for Vendor A and Vendor B (same workflow shape), so genuinely different ordered workflows are not exercised end-to-end.                                                                                                    |
| Missing customer               | Reject or fail validation without execution.                                  | Implemented as customer-validation failure: an invalid/unknown beneficiary persists`FAILED` without vendor submission. There is no separate "customer record missing" concept.                                                                                                                                                          |
| Unsupported product            | Report no applicable capability; do not execute.                              | Implemented. Capability lookup finds no executable capability; the MCP tool returns a structured error and`/api/chat` returns HTTP 400 without execution.                                                                                                                                                                               |
| Prepaid insufficient balance   | Return structured deterministic denial before vendor selection or submission. | Implemented for the configured demo account.                                                                                                                                                                                                                                                                                              |
| Postpaid credit limit exceeded | Record deterministic execution failure.                                       | Planned. Current behavior is**not** a credit-limit check: with no postpaid policy configured, the policy engine unconditionally denies any `POSTPAID` request with "Postpaid policy is not configured".                                                                                                                           |
| Vendor timeout →`UNKNOWN`   | Preserve ambiguity rather than mark`FAILED`.                                | Implemented. Submission uncertainty persists`UNKNOWN` (state machine + durable `SUBMITTING` boundary); the demo `TIMEOUT` scenario simulates the vendor timeout. No chat-triggered recovery flow.                                                                                                                                   |
| `UNKNOWN` → `SUCCESS`     | Investigate with a status query and resolve success.                          | Implemented at the deterministic engine/MCP level:`get_transaction_status` / recovery reconciliation queries the vendor and resolves `STATUS_RESOLVED` → `SUCCESS`. Not yet triggered from a conversational flow.                                                                                                                  |
| `UNKNOWN` → `FAILED`      | Investigate with a status query and resolve failure.                          | Implemented at the deterministic engine/MCP level: recovery reconciliation queries the vendor and records`FAILED`. Not yet triggered from a conversational flow.                                                                                                                                                                        |
| Duplicate prevention           | Prevent duplicate financial/product delivery during retries and ambiguity.    | Partially implemented. Same-key replay and`UNKNOWN` replay do not resubmit, and a database uniqueness constraint prevents duplicate records. The conversational path generates a new idempotency key per request, so cross-request duplicate prevention is not established (see the safety findings reported with this reconciliation). |

## POSTPAID behavior note

POSTPAID requests are denied because postpaid policy is **not configured**, not because a
credit limit was exceeded. The account context model supports a `POSTPAID` account type,
but the policy engine has no postpaid rule set, so it returns a deterministic denial with
the reason "Postpaid policy is not configured" for any POSTPAID request. The "Postpaid
credit limit exceeded" row above describes intended future behavior once a postpaid policy
exists; today no credit-limit evaluation occurs.

## Future retry-safety scenario — not implemented

```text
UNKNOWN → status query → FAILED → deterministic retry policy → ask user before retry
```

A confirmed failure is not by itself permission to retry. Any future retry must be
allowed by deterministic policy and explicitly confirmed by the user.
