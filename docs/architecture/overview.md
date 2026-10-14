# Architecture Overview

## Principle

> LLM reasons; deterministic application controls and executes.

The system separates conversational reasoning from execution authority. The agent may propose an action, but deterministic application services validate it, apply policy, execute through controlled vendor adapters, and record the transaction outcome.

## Current implemented foundation

- Python 3.12 FastAPI backend with a health endpoint, a narrow Vendor A-backed `POST /transactions` vertical slice, and a conversational `POST /api/chat` boundary.
- PostgreSQL, SQLAlchemy, and Alembic migrations.
- Canonical transaction ORM/domain model and explicit transaction state machine.
- Vendor adapter contract and deterministic in-memory Vendor A and Vendor B MTN airtime adapters.
- In-memory transaction execution service plus a persistence-aware execution service.
- Globally unique optional transaction idempotency keys, a durable `SUBMITTING` boundary, query-only recovery, and separate PostgreSQL Vendor A and Vendor B simulator operation ledgers.
- Canonical capability domain model, PostgreSQL persistence, deterministic registry lookup, and seeded Vendor A and Vendor B MTN airtime capabilities.
- Deterministic multi-vendor routing with runtime/scenario vendor availability and a deterministic preference order.
- Minimal planner boundary with deterministic plan validation behind the `LLMProvider` contract; a deterministic demo planner provider drives the local/demo path and a Bedrock Converse provider implements the same contract.
- MCP Streamable HTTP boundary exposing the business tools `find_transaction_capabilities`, `execute_transaction`, and the read-only `get_transaction_status`.
- Natural-language `RequestUnderstanding` that converts a message into a validated `AgentRequest` without vendor selection, policy, routing, or execution authority.
- Conversational HTTP boundary (`POST /api/chat`) that parses a message, runs the existing `AgentRuntime`/`TransactionOrchestrator` path through an in-process MCP session, and returns the authoritative `AgentResult` plus its deterministic explanation.
- Additive multi-turn conversation mode on `POST /api/chat` (`mode="conversation"`, ADR-007) that collects missing airtime fields, requires explicit confirmation, and then dispatches through the same single execution path. Conversation state is single-process and in-memory, so it does not survive a restart or span multiple processes.
- Configuration-backed demo Account Context and deterministic prepaid balance policy, enforced after planner/capability validation and again at the MCP execution boundary.
- Deterministic transaction investigation and status reconciliation (via `get_transaction_status`), and a bounded server-side demo scenario API guarded by demo mode.
- Judge-facing React simulator that is presentation-only; the backend remains authoritative for policy, routing, execution, and outcomes.
- Deterministic `TransactionExplainer` that turns the canonical `AgentResult` into user-facing text without execution authority.
- Deterministic application-side construction and authentication of the allow-listed vendor adapters; credentials remain inside the application boundary.

### REST endpoint vs policy-enforced execution path

`POST /transactions` is a narrow, legacy Vendor A-backed vertical slice. It hard-codes
Vendor A in the request handler, constructs the Vendor A adapter directly, and executes
through the persistence service; it does **not** run the planner, the Switcher, or the
account policy guard. It is **not** equivalent to the policy-enforced MCP/orchestrator
path and must not be described as such. No repository evidence establishes that it is
retained for backward compatibility, so no such purpose is claimed here.

Agent and direct MCP execution use deterministic vendor routing. Policy denial stops
before vendor selection and MCP execution, and direct MCP execution is subject to the
same policy engine as the orchestrator. The repository currently contains no test
asserting that `POST /transactions` enforces the account policy guard.

### Planner candidate vendor authority

`planner_candidate_vendor` is advisory only. It records the vendor the planner
proposed, but the deterministic Switcher (`switcher/routing.py`) determines the vendor
that actually executes. The planner's candidate does not become the execution vendor,
is never trusted for routing decisions, and is overridden whenever the candidate is
ineligible or unavailable (for example, the `PLANNER_A_A_UNAVAILABLE` scenario, where
the planner proposes Vendor A but the Switcher selects Vendor B).

### Planner-visible business operations vs deterministic adapter lifecycle

`ExecutionPlan.steps` represents the planner-visible business operations required for the requested transaction. The planner does not need to reproduce every operation in a vendor's canonical workflow. `Capability.workflow` remains the authoritative description of the vendor's complete execution requirements, while deterministic validation checks that the required planner-visible business operations are represented in the plan.

In this model, `AUTHENTICATE` is a deterministic adapter/credential responsibility and is not required in the planner's execution plan. `QUERY_TRANSACTION` is a deterministic transaction-status/lifecycle responsibility and is not required in the initial planner execution plan. The deterministic execution and adapter layer remains responsible for these lifecycle and adapter operations.

Vendor adapter construction and authentication are application-controlled. The resolver accepts only the implemented vendor code, obtains credentials from application settings, and does not perform vendor selection or ranking. MCP and agent callers do not construct adapters or receive credentials.

## MCP boundary and transport

MCP (Model Context Protocol) is the structured boundary through which the
agent/application accesses approved business capabilities. It is the implemented
agent/backend integration surface. It is **not** an LLM, does not supply
transaction policy, and is **not** the Alexa+ integration.

- **Transport.** The MCP server is exposed over Streamable HTTP
  (`server.streamable_http_app(...)`) and mounted into the FastAPI app at `/mcp`
  (`apps/api/app/main.py`, `apps/api/app/mcp_server/app.py`). DNS-rebinding
  protection is enabled with an explicit loopback host allow-list.
- **Business tools.** The server exposes business-level tools rather than
  general-purpose transport tools:
  - `find_transaction_capabilities(service_type, product_type, network)` — exact
    capability discovery against the canonical capability registry.
  - `execute_transaction(...)` — executes a validated airtime transaction. It
    applies the deterministic account policy before capability lookup or vendor
    selection, then routes through the deterministic Switcher and the
    application-constructed vendor adapter.
  - `get_transaction_status(transaction_id)` — read-only status/investigation
    lookup for a persisted transaction; it never submits or retries.
- **Authority.** The deterministic application services remain authoritative for
  validation, policy, routing, execution, and transaction outcomes; the MCP tools
  are thin wrappers over them. Generic tools (`call_api`, `execute_http`, ...) are
  intentionally excluded (ADR-005).
- **In-process use.** `POST /api/chat` opens an in-process MCP session against the
  host application's server, so the same boundary serves both external MCP
  clients and the conversational API without a second execution path.

This boundary lets a future conversational or voice client use approved
capabilities, but it does not itself make Alexa+ a current capability.

## Voice I/O

- **Voice output.** Functional and frontend-only. The judge-facing app speaks the
  authoritative assistant response using the browser Web Speech API (Speech
  Synthesis) and lets the user choose **Text only** or **Text + spoken**
  presentation. Speech is derived from the backend response; it does not change
  transaction execution, policy, routing, or confirmation requirements, and the
  text transcript remains authoritative.
- **Voice input.** Implemented under `frontend/src/voice/` (Web Speech API
  recognition) but disabled by configuration: `VOICE_INPUT_ENABLED = false` in
  `frontend/src/config.ts`, so the demo accepts typed requests. Testing surfaced
  unacceptable ambiguity around transaction amounts and recipient identifiers;
  for a financial instruction the agent must not guess. See the friction log
  (`docs/feedback/amazon-friction-log.md`) for the recorded investigation.
- **Design principle.** Refuse or ask for clarification rather than fabricate
  intent. This mirrors ADR-003's `UNKNOWN`-is-not-`FAILED` philosophy, while
  noting that ambiguous speech input and an ambiguous transaction outcome are
  different failure modes.
- **Future direction.** An Alexa+-style simulated experience and any actual
  Alexa+ integration remain separate planned work and are **not** implemented.

## LLM provider boundary and demo inference

- The planner boundary is defined by the `LLMProvider` contract
  (`agent/llm_provider.py`): a provider turns a prompt into a
  Pydantic-validated structured output.
- `BedrockProvider` (`agent/bedrock_provider.py`, AWS Bedrock Converse via
  `boto3`) implements that contract and is covered by unit tests
  (`tests/unit/agent/test_bedrock_provider.py`). It requires `BEDROCK_MODEL_ID`
  (and an AWS region) to be configured and raises a clear error otherwise.
- The running demo does **not** call Bedrock. `POST /api/chat` wires the
  deterministic `DeterministicPlannerProvider`, so request understanding,
  planning, policy, routing, investigation, and explanation perform no model
  inference. Implementing a provider does not mean the running product already
  uses it.

## Intended complete architecture

```text
User (planned Alexa+ voice)
    ↓
MCP boundary
    ↓
Agent Orchestrator
    ↓
Planner / Investigator / Explainer
    ↓
Capability Engine + Account Context + Live State
    ↓
Plan Validation
    ↓
Policy Engine
    ↓
Switcher Core
    ↓
Vendor Adapters
    ↓
Transaction State Machine
    ↓
Observability / Investigation
    ↓
Explanation
```

The MCP transport and business tools, request understanding, conversational API boundary, planner boundary, agent orchestration, deterministic multi-vendor routing, demo account context, deterministic prepaid policy, transaction investigation, and the `LLMProvider` contract with its Bedrock Converse implementation are implemented. On the client, voice output (browser Speech Synthesis over the authoritative response) is implemented, while voice input is built but disabled for the demo build. Alexa+-style voice integration, live account administration, postpaid policy, and observability remain planned. MCP is the implemented integration boundary; Alexa+ is not implemented and must not be claimed.

The deterministic `TransactionExplainer` accepts the existing `AgentResult` and returns a user-facing string. It has no execution authority and does not call the runtime, MCP, Switcher, policy engine, vendors, or transaction services.
