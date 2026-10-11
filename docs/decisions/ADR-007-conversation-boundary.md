# ADR-007: Bounded Conversation Boundary

**Status:** Implemented (single-process, in-memory conversation state)

## Decision

Multi-turn airtime requests are handled by a bounded conversation layer that
collects missing details and requires an explicit confirmation before executing
through the existing transaction engine. Conversation state is application
state, not transaction state; it is held in memory in a single process and is
not persisted.

`POST /api/chat` gains an additive conversation mode (`mode: "conversation"`).
The legacy immediate-execution contract (`mode: "execute"`, the default) is
unchanged for existing clients.

## Conversation state machine

```text
COLLECTING → AWAITING_CONFIRMATION → EXECUTING → COMPLETE | CANCELLED
```

`COMPLETE` and `CANCELLED` are terminal. A terminal conversation accepts no
further turns and cannot be restarted or repurposed. Conversation progress is
never encoded in the transaction's `status`; an authoritative outcome appears
only in the execution `result`.

## Single execution path

The conversation layer never executes a transaction itself. A confirmed turn is
dispatched through the same `RequestUnderstanding` → `AgentRuntime` →
`TransactionOrchestrator` → policy → MCP path used by the immediate-execution
mode. There is no second execution path, and no new policy or routing logic.

## Explicit confirmation

Clarification and confirmation turns never fabricate a result and never imply a
denial. Execution happens only after a user turn that explicitly confirms the
summarized request. Repeated or concurrent confirmations execute at most once
per conversation; the cached result is replayed for any repeat.

## Truthful outcomes

Execution preserves the existing outcome semantics. `UNKNOWN` remains distinct
from failure, a known transaction id is retained, and an uncertain submission is
never automatically retried.

### Execution errors before versus after possible side effects

The confirmed request runs through `execute_chat`; every exception is classified
by what the transaction engine can prove, not by assumption:

- **Before any side effect.** `UnsupportedRequestError` (parser rejection) and
  `UnsupportedTransactionCapabilityError` (discovery returned no executable
  capability) are raised before the MCP execution tool is ever called. The
  conversation resets to `AWAITING_CONFIRMATION` and the error is surfaced to the
  client (HTTP 400). The user may revise and confirm again; this is the only case
  where a second execution attempt is permitted.
- **Possibly after a side effect.** Every other failure — including an opaque
  MCP tool error, an invalid agent result, and any unexpected exception — may
  have happened before or after the vendor submission. The existing MCP error
  contract does not distinguish these, and it does not return the persisted
  transaction identity. Because the side-effect state cannot be proven, the
  conversation **never retries**, records a truthful `UNKNOWN` result, and
  becomes terminal (`COMPLETE`). Cancellation or interpreter shutdown during
  execution is handled the same way before the exception propagates, so a
  conversation is never left stuck in `EXECUTING`.

No path fabricates a `success` or `failed` outcome. When the pipeline does
return an authoritative result — including the vendor-timeout `UNKNOWN` result,
which carries a real transaction id — that result and its id are cached and
replayed verbatim.

## Concurrency guarantees

Each conversation owns an `asyncio.Lock`, and the store holds a registry lock
only while looking up/creating entries and adjusting an `active` reference count.

- Two concurrent confirmations for the same conversation are serialized: at most
  one execution occurs, both responses observe the same cached result, and an
  uncertain (or otherwise terminal) conversation cannot be retried by the second
  confirmation.
- These guarantees are **process-local**. They rely on `asyncio` locks in a
  single event loop and are not a distributed lock.

## Capacity

The store is strictly bounded by `max_conversations`. A new conversation is only
created if the store can make room by evicting an eligible conversation or is
below the bound:

- Only idle (`active == 0`), fully resolved terminal conversations are evictable.
  A `COMPLETE` conversation whose outcome is `unknown`, any non-terminal
  conversation, and any in-use conversation are never evicted.
- Expired eligible conversations are reaped first (time-to-live); otherwise an
  eligible conversation is evicted only to satisfy the bound.
- When the store is full and no eligible conversation can be evicted (for
  example, every conversation is active or awaiting investigation), creating a
  new conversation is rejected with a clear `503` response. This is a transient
  capacity condition; no conversation and no transaction is created, so the
  client is never told that a transaction failed or succeeded.

## Limitations — in-memory scope

This design deliberately does not solve cross-process or restart durability:

- Deduplication, capacity, and replay apply **only within a single process**.
  Two API processes do not share conversation state, so a repeated confirmation
  routed to a different process is not deduplicated by this layer. The
  underlying transaction idempotency remains the backstop.
- Conversation state **does not survive a process restart**. A conversation id
  from a previous process is unknown and is rejected.
- **No automatic investigation or recovery.** When an execution error leaves the
  outcome unknown and the persisted transaction identity was not returned by the
  MCP error contract, the conversation can report `UNKNOWN` but cannot itself
  locate or reconcile the transaction. Investigation of that transaction (for
  example via the read-only transaction-status tool) is a separate, manual
  concern; this layer makes no claim to recover it.
- A store full of active or unresolved conversations rejects new conversations
  until those conversations become eligible for eviction or are cleared.

Conversation state is not a system of record. The transaction engine and its
persistence remain authoritative; this layer only sequences a request.
