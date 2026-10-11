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

The MCP transport and business tools, request understanding, conversational API boundary, planner boundary, agent orchestration, deterministic multi-vendor routing, demo account context, deterministic prepaid policy, transaction investigation, and the `LLMProvider` contract with its Bedrock Converse implementation are implemented. Alexa+ voice integration, live account administration, postpaid policy, and observability remain planned. MCP is the implemented integration boundary; Alexa+ is not implemented and must not be claimed.

The deterministic `TransactionExplainer` accepts the existing `AgentResult` and returns a user-facing string. It has no execution authority and does not call the runtime, MCP, Switcher, policy engine, vendors, or transaction services.
