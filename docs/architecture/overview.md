# Architecture Overview

## Principle

> LLM reasons; deterministic application controls and executes.

The system separates conversational reasoning from execution authority. A future agent may propose an action, but deterministic application services validate it, apply policy, execute through controlled vendor adapters, and record the transaction outcome.

## Current implemented foundation

- Python 3.12 FastAPI backend with a health endpoint and a Vendor A-backed `POST /transactions` vertical slice.
- PostgreSQL, SQLAlchemy, and Alembic migrations.
- Canonical transaction ORM/domain model and explicit transaction state machine.
- Vendor adapter contract and deterministic in-memory Vendor A MTN airtime adapter.
- In-memory transaction execution service plus a persistence-aware execution service.
- Globally unique optional transaction idempotency keys, a durable `SUBMITTING` boundary, query-only recovery, and a separate PostgreSQL Vendor A simulator operation ledger.
- Canonical capability domain model, PostgreSQL persistence, deterministic registry lookup, and seeded Vendor A MTN airtime capability.
- Minimal planner boundary with deterministic plan validation and a Bedrock provider.
- MCP Streamable HTTP boundary exposing canonical capability discovery and transaction execution.
- Configuration-backed demo Account Context and deterministic prepaid balance policy, enforced after planner/capability validation and again at the MCP execution boundary.
- Deterministic application-side construction and authentication of the allow-listed Vendor A adapter; credentials remain inside the application boundary.

The standalone transaction endpoint remains deliberately narrow. Agent execution uses deterministic vendor routing; policy denial stops before vendor selection and MCP execution, and direct MCP execution is subject to the same policy engine.

### Planner-visible business operations vs deterministic adapter lifecycle

`ExecutionPlan.steps` represents the planner-visible business operations required for the requested transaction. The planner does not need to reproduce every operation in a vendor's canonical workflow. `Capability.workflow` remains the authoritative description of the vendor's complete execution requirements, while deterministic validation checks that the required planner-visible business operations are represented in the plan.

In this model, `AUTHENTICATE` is a deterministic adapter/credential responsibility and is not required in the planner's execution plan. `QUERY_TRANSACTION` is a deterministic transaction-status/lifecycle responsibility and is not required in the initial planner execution plan. The deterministic execution and adapter layer remains responsible for these lifecycle and adapter operations.

Vendor adapter construction and authentication are application-controlled. The resolver accepts only the implemented vendor code, obtains credentials from application settings, and does not perform vendor selection or ranking. MCP and agent callers do not construct adapters or receive credentials.

## Intended complete architecture

```text
User / Alexa+
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

The MCP transport, capability and execution tools, planner boundary, agent orchestration, demo account context, deterministic prepaid policy, transaction investigation, and Bedrock provider are implemented. Live account administration, postpaid policy, observability, and user-facing explanation remain planned.
