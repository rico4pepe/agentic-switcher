# Architecture Overview

## Principle

> LLM reasons; deterministic application controls and executes.

The system separates conversational reasoning from execution authority. A future agent may propose an action, but deterministic application services validate it, apply policy, execute through controlled vendor adapters, and record the transaction outcome.

## Current implemented foundation (through 4G)

- Python 3.12 FastAPI backend with a health endpoint and a Vendor A-backed `POST /transactions` vertical slice.
- PostgreSQL, SQLAlchemy, and Alembic migrations.
- Canonical transaction ORM/domain model and explicit transaction state machine.
- Vendor adapter contract and deterministic in-memory Vendor A MTN airtime adapter.
- In-memory transaction execution service plus a persistence-aware execution service.
- Canonical capability domain model, PostgreSQL persistence, deterministic registry lookup, and seeded Vendor A MTN airtime capability.

The current endpoint is deliberately narrow: Vendor A is explicitly wired, and no routing, policy, agent, MCP, or investigation execution flow exists yet.

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

Everything below is planned unless listed in the current implemented foundation. In particular, the MCP boundary, agent orchestration, planner/investigator/explainer, account context, live state, policy engine, observability, and user-facing explanation are not implemented.
