# Engineering Challenges and Decisions

This document records the hard problems in Agentic Switcher's orchestration core
and the decisions that resolved them, with the code, tests, and ADRs that enforce
each one. It is written for a reviewer who wants to know *why* the system behaves
the way it does, not just *what* it does.

It is evidence-based. Every entry points at the enforcement site, the tests that
prove it, and the trade-offs that remain. Claims that are only recorded in the
development history (rather than re-verified against the current tree) are
quarantined in [Historical findings](#historical-findings-from-earlier-milestone-reviews)
at the end and labeled as such.

Each entry uses the same structure:

1. **Problem / risk** — what could go wrong.
2. **Decision** — what we chose.
3. **Implementation enforcement** — where the decision lives in code.
4. **Tests / ADRs** — the evidence.
5. **Trade-offs / remaining limitations** — what the decision does not solve.

## Index

- [1. Policy enforcement a direct MCP caller cannot bypass](#1-policy-enforcement-a-direct-mcp-caller-cannot-bypass)
- [2. The MCP execution boundary does not accept a caller-controlled vendor](#2-the-mcp-execution-boundary-does-not-accept-a-caller-controlled-vendor)
- [3. Deterministic vendor selection; the planner candidate is advisory](#3-deterministic-vendor-selection-the-planner-candidate-is-advisory)
- [4. Explicit, button-only confirmation](#4-explicit-button-only-confirmation)
- [5. Preserving details across conversation turns](#5-preserving-details-across-conversation-turns)
- [6. Errors before versus after possible side effects](#6-errors-before-versus-after-possible-side-effects)
- [7. UNKNOWN is not FAILED](#7-unknown-is-not-failed)
- [8. Idempotency without a false exactly-once promise](#8-idempotency-without-a-false-exactly-once-promise)
- [9. Concurrency guarantees are process-local](#9-concurrency-guarantees-are-process-local)
- [10. Conversation capacity preserves unresolved transactions](#10-conversation-capacity-preserves-unresolved-transactions)
- [11. Truthful, sanitized MCP observability](#11-truthful-sanitized-mcp-observability)
- [12. Truthful outcome wording in the UI](#12-truthful-outcome-wording-in-the-ui)
- [13. Capability operations versus deterministic adapter lifecycle](#13-capability-operations-versus-deterministic-adapter-lifecycle)
- [14. Voice input safety](#14-voice-input-safety)
- [Historical findings from earlier milestone reviews](#historical-findings-from-earlier-milestone-reviews)

---

## 1. Policy enforcement a direct MCP caller cannot bypass

- **Problem / risk.** There are two ways a transaction reaches the engine: the
  orchestrator path (`POST /api/chat` → `AgentRuntime` → `TransactionOrchestrator`)
  and a direct MCP `execute_transaction` call. If the account/policy guard were
  applied at only one of them, or if it could be influenced by the model, an agent
  (or a client) could execute past the intended limit.
- **Decision.** Policy is deterministic and independent of the LLM, and it is
  evaluated at *both* boundaries before any side effect. A denial stops before
  capability lookup or vendor selection.
- **Implementation enforcement.** `policy/engine.py:35`
  (`PolicyEngine.evaluate(beneficiary, amount)`) reads only account facts from the
  demo account context — it does not consult planner output. The orchestrator
  evaluates policy at `agent/orchestrator/service.py:262`, after capability
  discovery and plan validation but before execution. The MCP tool evaluates the
  same engine *first* at `apps/api/app/mcp_server/app.py:148` and returns a
  structured denial (`status: "denied"`) without opening a session or touching the
  capability registry.
- **Tests / ADRs.** `tests/integration/test_mcp_execution.py::test_mcp_policy_denial_is_structured_and_stops_direct_execution`
  (a denied direct call performs no capability lookup and no vendor submission);
  `tests/integration/test_mcp_tool_boundary.py` (only declared inputs are
  accepted). See ADR-004 (agent execution boundary), ADR-005 (business-level MCP
  tools), and the "Prepaid insufficient balance" row in
  [`docs/scenarios/transaction-scenarios.md`](../scenarios/transaction-scenarios.md).
- **Trade-offs / remaining limitations.** The rule set is small: a deterministic
  prepaid balance check for the configured demo account. POSTPAID is denied
  because no postpaid policy exists yet, not because a credit limit was exceeded.
  Customer consent capture is not implemented.

## 2. The MCP execution boundary does not accept a caller-controlled vendor

- **Problem / risk.** If the `execute_transaction` schema accepted a `vendor_code`
  that flowed into selection, a caller could steer execution to a vendor of its
  choosing — bypassing the deterministic Switcher entirely. This was a genuine
  hole found during an earlier red-team review (see historical findings).
- **Decision.** Vendor selection is application-determined. The tool derives the
  vendor internally; the field is not part of the callable schema and cannot be
  injected.
- **Implementation enforcement.** `apps/api/app/mcp_server/app.py:143`
  (`_execute_transaction`) no longer takes a `vendor_code` parameter; it derives
  the vendor at `:183` via `resolve_execution_vendor_code`. The advertised tool
  schema removes `vendor_code` from properties and from the required list at
  `:371`.
- **Tests / ADRs.** `tests/integration/test_mcp_execution.py::test_mcp_rejects_internal_vendor_override_keyword`
  and `::test_mcp_execute_schema_exposes_only_business_inputs`;
  `tests/integration/test_mcp_tool_boundary.py::test_undeclared_arguments_cannot_influence_vendor_selection`;
  `tests/unit/agent/test_mcp_client_tools.py::test_omitted_vendor_code_is_not_injected_into_the_recorded_call`.
  See ADR-005.
- **Trade-offs / remaining limitations.** A caller cannot pin a vendor at all.
  That is the intended behavior for this boundary; any future legitimate need for
  operator-directed routing would have to be expressed as policy, not as an
  arbitrary caller field.

## 3. Deterministic vendor selection; the planner candidate is advisory

- **Problem / risk.** Two failure modes: (a) if the LLM's proposed vendor were
  authoritative, a model preference could pick an unavailable vendor or abort the
  transaction; (b) a "first executable capability" fallback would make routing
  depend on registry ordering rather than a rule.
- **Decision.** The Switcher determines the executing vendor by a fixed priority
  order over capabilities that are simultaneously executable, plan-compatible, and
  runtime-available. The planner's `candidate_vendor` is recorded but never
  authoritative; if it is unavailable the Switcher falls through to an eligible
  vendor, and if none is eligible it raises rather than silently guessing.
- **Implementation enforcement.** `switcher/routing.py:75-87`
  (`resolve_execution_vendor_code` filters and selects by `DEFAULT_VENDOR_PRIORITY`,
  raising when nothing is eligible). The orchestrator discards the candidate at
  `agent/orchestrator/service.py:283` and calls the resolver; the MCP tool
  recomputes routing independently at `apps/api/app/mcp_server/app.py:183`. See
  "Planner candidate vendor authority" in
  [`docs/architecture/overview.md`](../architecture/overview.md).
- **Tests / ADRs.** `tests/unit/agent/test_orchestrator.py::test_candidate_vendor_does_not_override_deterministic_priority`
  and `::test_candidate_vendor_unavailable_falls_through_in_orchestrator`;
  `tests/integration/test_chat_conversation.py::test_vendor_fallback_is_selected_after_confirmation`;
  `tests/integration/test_mcp_execution.py::test_mcp_candidate_vendor_falls_through_to_priority_vendor_when_unavailable`.
- **Trade-offs / remaining limitations.** Priority is a hard-coded demo order
  (`vendor_a` before `vendor_b`); there is no cost, latency, or success-rate
  optimization. Only MTN airtime capabilities are seeded, so genuinely different
  workflow shapes are not exercised end-to-end.

## 4. Explicit, button-only confirmation

- **Problem / risk.** If confirmation were inferred from free text, a stray "yes",
  "ok", or "confirm" could execute a financial instruction — and a stray "cancel"
  could abort one. The agent must never guess consent.
- **Decision.** Confirmation and cancellation are explicit *control actions*,
  mutually exclusive with a free-text message, and validated against the
  conversation's actual state. The browser emits one only when the corresponding
  button is pressed.
- **Implementation enforcement.** `apps/api/app/chat_contracts.py:28`
  (`ChatAction`) and the `_require_message_or_action` validator at `:58` reject a
  message sent with an action, an action outside conversation mode, or an action
  without a `conversation_id`. The frontend only calls `confirmConversation` /
  `cancelConversation` from the button handlers (`frontend/src/App.tsx:244`,
  `frontend/src/api.ts`).
- **Tests / ADRs.** `tests/unit/app/test_conversations.py::test_typed_affirmative_never_executes_a_pending_transaction`,
  `::test_typed_negative_never_cancels_a_pending_transaction`,
  `::test_confirm_action_on_a_non_pending_conversation_is_rejected`,
  `::test_cancel_action_cancels_without_executing`; `tests/integration/test_chat_conversation.py::test_action_and_message_are_mutually_exclusive`,
  `::test_action_is_rejected_in_execute_mode`. See ADR-007.
- **Trade-offs / remaining limitations.** Confirmation is button-driven; a user
  cannot confirm by typing an affirmative. This is a deliberate UX cost paid for
  safety.

## 5. Preserving details across conversation turns

- **Problem / risk.** A user supplies missing fields over several turns. Details
  must accumulate without being lost, and a new request arriving during
  confirmation must not silently overwrite the pending transaction.
- **Decision.** The conversation layer keeps an accumulating draft. A pending
  confirmation is protected: an off-topic or new message during confirmation
  cannot overwrite it, and unrelated messages outside confirmation redirect
  without discarding collected details.
- **Implementation enforcement.** `apps/api/app/conversations.py` (conversation
  store and turn handling) and `ConversationDraft` in
  `apps/api/app/chat_contracts.py:95`.
- **Tests / ADRs.** `tests/unit/app/test_conversations.py::test_spaced_beneficiary_is_preserved_across_separate_turns`,
  `::test_new_request_during_confirmation_cannot_overwrite_pending_transaction`,
  `::test_off_topic_message_during_confirmation_keeps_pending_transaction`,
  `::test_off_topic_message_outside_confirmation_redirects_without_losing_details`;
  `tests/integration/test_chat_conversation.py::test_multi_turn_amount_then_beneficiary_reaches_confirmation`,
  `::test_multi_turn_network_then_amount_reaches_confirmation`. See ADR-007.
- **Trade-offs / remaining limitations.** The draft lives in single-process,
  in-memory conversation state; it does not survive a restart.

## 6. Errors before versus after possible side effects

- **Problem / risk.** A failure can happen before a vendor submission or after it.
  The MCP error contract does not distinguish the two and does not return the
  persisted transaction identity. Retrying after an uncertain side effect risks
  duplicate execution.
- **Decision.** Classify every exception by what the engine can *prove*, not by
  assumption. Errors that provably precede any side effect reset the conversation
  to awaiting confirmation (the only case where a second attempt is allowed).
  Anything that might follow a side effect produces a truthful `UNKNOWN`, is
  terminal, and is never retried.
- **Implementation enforcement.** `apps/api/app/conversations.py` execution error
  handoff and `agent/orchestrator/mcp_events.py:168` (`attach_events`, which
  carries the real calls onto the error so the `UNKNOWN` result still shows what
  happened). Full classification in ADR-007 §"Execution errors before versus after
  possible side effects".
- **Tests / ADRs.** `tests/unit/app/test_conversations.py::test_pre_execution_error_resets_to_awaiting_confirmation`,
  `::test_pre_side_effect_parser_error_resets_to_awaiting_confirmation`,
  `::test_unexpected_execution_error_terminates_as_unknown_not_stuck`,
  `::test_cancellation_during_execution_is_terminal_and_not_retried`;
  `tests/integration/test_chat_conversation.py::test_error_after_persistence_reports_unknown_without_retry`.
- **Trade-offs / remaining limitations.** An `UNKNOWN` result may be reported even
  when the transaction in fact failed. That is the honest choice: the engine
  cannot prove failure, so it does not claim it.

## 7. UNKNOWN is not FAILED

- **Problem / risk.** A vendor timeout does not prove failure. Marking it `FAILED`
  would mislead, and blindly retrying an ambiguous submission could double-charge.
- **Decision.** An ambiguous submission is recorded as `UNKNOWN`, never `FAILED`.
  It is never automatically retried; investigation resolves it later through
  `INVESTIGATING → STATUS_RESOLVED → SUCCESS | FAILED`.
- **Implementation enforcement.** `apps/api/app/domain/state_machine.py:13-48`
  (`SUBMITTING → UNKNOWN`, `UNKNOWN → INVESTIGATING`, `INVESTIGATING →
  STATUS_RESOLVED | UNKNOWN`); `switcher/transactions/investigator.py`; the
  read-only `get_transaction_status` MCP tool.
- **Tests / ADRs.** ADR-003 (`docs/decisions/ADR-003-unknown-not-failed.md`);
  `tests/unit/app/test_conversations.py::test_uncertain_execution_yields_unknown_without_retry`,
  `::test_known_transaction_id_is_preserved_on_uncertain_result`;
  `tests/integration/test_chat_conversation.py::test_timeout_unknown_is_preserved_without_retry`;
  `tests/integration/test_mcp_execution.py::test_mcp_get_transaction_status_resolves_unknown_transaction`.
- **Trade-offs / remaining limitations.** Investigation is an engine/MCP-level,
  manual capability; it is not driven from the conversational flow, and no retry
  policy or user-confirmation retry flow exists.

## 8. Idempotency without a false exactly-once promise

- **Problem / risk.** A retried request or a repeated confirmation could resubmit
  and duplicate a transaction. A blanket "exactly once" claim would be false.
- **Decision.** Idempotency is scoped to a caller-supplied key with matching
  business inputs: replay resumes the existing transaction instead of
  resubmitting, and a database uniqueness constraint is the backstop. A duplicate
  confirmation within a conversation replays the cached result.
- **Implementation enforcement.** `switcher/transactions/persistence_service.py:46-65`
  (resume by key) and `:340-348` (`_assert_same_business_inputs`); the
  orchestrator generates a key per request at `agent/orchestrator/service.py:291`;
  the MCP tool requires a key (`apps/api/app/mcp_server/app.py:95`).
- **Tests / ADRs.** `tests/unit/app/test_conversations.py::test_repeated_confirmation_replays_cached_result`,
  `::test_concurrent_confirmations_execute_at_most_once`;
  `tests/integration/test_mcp_execution.py::test_mcp_same_key_replay_reuses_transaction_without_another_submission`,
  `::test_mcp_same_key_different_inputs_returns_conflict_without_submission`,
  `::test_mcp_unknown_replay_does_not_resubmit`.
- **Trade-offs / remaining limitations.** The conversational path generates a
  **new** idempotency key per request, so re-stating the same intent as a fresh
  request is **not** deduplicated across requests. The same-input comparison covers
  product type, network, beneficiary, and amount; it does **not** include
  `service_type`. This is not a universal exactly-once guarantee.

## 9. Concurrency guarantees are process-local

- **Problem / risk.** Two concurrent confirmations for the same conversation could
  execute twice.
- **Decision.** Each conversation owns an `asyncio.Lock`, and the store holds a
  registry lock only while looking up/creating entries and adjusting an `active`
  reference count. At most one execution occurs per conversation, and both
  responses observe the same cached result. The scope is explicitly process-local.
- **Implementation enforcement.** `apps/api/app/conversations.py`; documented in
  ADR-007 §Concurrency guarantees.
- **Tests / ADRs.** `tests/unit/app/test_conversations.py::test_concurrent_confirmations_execute_at_most_once`,
  `::test_concurrent_confirmation_and_new_conversation_are_consistent`;
  `tests/integration/test_chat_conversation.py::test_concurrent_confirmations_execute_at_most_once`.
- **Trade-offs / remaining limitations.** These guarantees rely on `asyncio` locks
  in a single event loop and are not a distributed lock. Two API processes do not
  share conversation state; a confirmation routed to a different process is not
  deduplicated by this layer. The transaction idempotency key remains the backstop.

## 10. Conversation capacity preserves unresolved transactions

- **Problem / risk.** An unbounded conversation store leaks. Evicting the wrong
  conversation would discard the only handle to an unresolved (`UNKNOWN`)
  transaction that still needs investigation.
- **Decision.** The store is strictly bounded. Only idle, fully resolved terminal
  conversations are evictable; a `COMPLETE`-but-`unknown` conversation, any
  non-terminal conversation, and any in-use conversation are never evicted. When
  the store is full with nothing evictable, a new conversation is rejected with a
  clear `503` rather than dropping state.
- **Implementation enforcement.** `apps/api/app/conversations.py` capacity/eviction
  logic; documented in ADR-007 §Capacity.
- **Tests / ADRs.** `tests/integration/test_chat_conversation.py::test_conversation_capacity_exhaustion_returns_503`.
- **Trade-offs / remaining limitations.** A store full of active or unresolved
  conversations rejects new conversations until one becomes eligible for eviction.
  This is a transient capacity condition, and no transaction is created or
  misreported as a result.

## 11. Truthful, sanitized MCP observability

- **Problem / risk.** A "tool trace" that is scripted or derived from the scenario
  label would be theater. A trace that emitted raw events could leak credentials or
  personal data.
- **Decision.** Record only *actual* `tools/call` invocations, sanitize at the MCP
  boundary, and carry recorded events onto errors so an `UNKNOWN` result still shows
  the real calls.
- **Implementation enforcement.** `agent/orchestrator/mcp_events.py` (a per-request
  `MCPCallRecorder`, key-driven redaction/masking, and `attach_events`);
  `apps/api/app/chat.py:115-137` (creates the recorder and attaches events to the
  response or the error).
- **Tests / ADRs.** `tests/unit/agent/test_mcp_events.py::test_sensitive_keys_are_redacted_recursively`,
  `::test_personal_data_is_masked_not_shown_whole`, `::test_recorder_sequences_calls_and_extracts_transaction_id`,
  `::test_attach_events_carries_real_events_on_the_error`; `tests/unit/agent/test_mcp_client_tools.py`
  (real calls are recorded, idempotency key redacted). Frontend: `frontend/src/components/MCPActivityPanel.test.tsx`.
- **Trade-offs / remaining limitations.** Sanitization is key-driven: a secret
  placed under an unexpected key name would not be redacted. The trace shows call
  arguments and short results, not full payloads.

## 12. Truthful outcome wording in the UI

- **Problem / risk.** An unconfirmed outcome must never be presented as success or
  failure; doing so would be a false claim about a financial event.
- **Decision.** `UNKNOWN` is always labeled "Outcome unconfirmed" with neutral
  styling and success wording is reserved for confirmed success.
- **Implementation enforcement.** `frontend/src/App.tsx:45-62` (outcome label map).
- **Tests / ADRs.** `frontend/src/components/ResultPanel.test.tsx`; ADR-003.
- **Trade-offs / remaining limitations.** Neutral styling is less "finished"
  looking than a green success badge. That is intentional.

## 13. Capability operations versus deterministic adapter lifecycle

- **Problem / risk.** Conflating the vendor adapter's internal lifecycle
  (`AUTHENTICATE`, credential handling) with the planner's business operations
  would make plans brittle, vendor-coupled, and hard to validate.
- **Decision.** `ExecutionPlan.steps` represents planner-visible business
  operations; the adapter lifecycle (`AUTHENTICATE`, `QUERY_TRANSACTION`) stays a
  deterministic adapter responsibility. Capability `workflow` remains the
  authoritative description of the vendor's full requirements, and plan validation
  checks that the required business operations are represented.
- **Implementation enforcement.** `docs/architecture/overview.md`
  §"Planner-visible business operations vs deterministic adapter lifecycle";
  `agent/orchestrator/service.py` (adapter construction stays in the application
  boundary).
- **Tests / ADRs.** `tests/unit/agent/test_execution_plan.py`;
  `tests/unit/vendors/test_vendor_a_capability.py::test_vendor_a_canonical_capability_preserves_workflow_order`.
- **Trade-offs / remaining limitations.** Only one workflow shape is seeded
  (MTN airtime for both vendors), so the generality of this separation is not yet
  exercised by a genuinely different ordered workflow end-to-end.

## 14. Voice input safety

- **Problem / risk.** Speech recognition introduces ambiguity around transaction
  amounts and recipient identifiers. For a financial instruction, guessing intent
  is unacceptable.
- **Decision.** Disable voice input for the demo build and require typed input;
  keep the recognition adapter in the tree but off by configuration.
- **Implementation enforcement.** `frontend/src/config.ts` (`VOICE_INPUT_ENABLED = false`);
  the adapter lives under `frontend/src/voice/`. Rationale in
  [`docs/feedback/amazon-friction-log.md`](../feedback/amazon-friction-log.md).
- **Tests / ADRs.** `frontend/src/App.responseMode.test.tsx` (asserts the "voice
  input is turned off for this demo" state) and the recognition behavior in
  `frontend/src/App.voice.test.tsx` / `frontend/src/components/VoiceInput.test.tsx`.
- **Trade-offs / remaining limitations.** No hands-free input in the demo. Voice
  *output* remains enabled and is derived from the authoritative backend response.

---

## Historical findings from earlier milestone reviews

These items come from the development history (recorded in KiloCode session
history) and are included for context. They are **historical**: the fixes are
reflected in the current tree and its tests (see §2 and §3), but the review
transcripts themselves are not part of this repository and were not re-run here.
Do not treat them as current verified behavior beyond what the linked tests show.

- **4I-I-B red-team review — two MUST FIX items on the MCP execution boundary.**
  1. *MCP execution bypass via a caller-controlled `vendor_code`.* A `vendor_code`
     field remained an accepted input and could steer execution away from the
     deterministic Switcher. Resolved by deriving the vendor inside the executor
     and removing the field from the callable schema (now §2).
  2. *Planner-proposed unavailable vendor aborted the transaction.* Routing raised
     instead of falling through when the planner's candidate was unavailable.
     Resolved by treating the candidate as advisory and falling through to priority
     selection (now §3).
  The review progressed from "APPROVED WITH ONE MUST FIX" to confirmation that both
  were verifiable, with the two missing regression tests (the bypass guard and the
  Scenario C fall-through) added.
- **4I-J policy review — "APPROVED — STOP REVIEW LOOP."** Confirmed the policy
  engine is deterministic and LLM-independent and is enforced at both the direct
  MCP boundary and the orchestrator boundary before any side effect (now §1).
- **4I-L request-understanding review — "APPROVED — STOP REVIEW LOOP."** Confirmed
  parser fixes: `5000` is no longer truncated to `500`, a beneficiary such as
  `08030000001` is never interpreted as an amount, and `-₦5000` is rejected rather
  than silently converted. The layer performs no vendor selection, routing, policy,
  or execution.

If any of these historical statements matters to your review, treat the linked
tests in §2, §3, and §1 as the current source of truth.
