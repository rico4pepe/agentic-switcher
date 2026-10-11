# Agentic Switcher

Agentic transaction orchestration and operations platform.

## Overview

Agentic Switcher explores how an AI agent can understand heterogeneous transaction capabilities, construct a safe execution plan, orchestrate transactions through controlled business tools, monitor transaction state, investigate ambiguous outcomes, and explain the result conversationally.

The system is designed around a clear separation of responsibilities:

> The agent reasons about what should happen; deterministic application services decide what is allowed to happen; the Switcher determines where the transaction should execute; the vendor executes it; the transaction engine determines what actually happened.

The core product principle is:

> **The user chooses WHAT. The agent understands HOW. The Switcher determines WHERE. The vendor executes. The transaction engine determines WHAT ACTUALLY HAPPENED.**

## Current Status

### Historical Foundation — Repository + FastAPI (Phase 4A)

This is the original scaffold, retained as historical context. It predates the
current milestone progression (4I/4J) and does not represent the current feature set.

- [X] Python 3.12 environment
- [X] Project virtual environment
- [X] Git repository
- [X] FastAPI application
- [X] Health endpoint
- [X] OpenAPI / Swagger documentation

### Phase 4B–4H — Core Platform Foundation

- [X] 4B — PostgreSQL + SQLAlchemy + Alembic
- [X] 4C — Domain Models
- [X] 4D — Transaction State Machine
- [X] 4E — Vendor Adapters
- [X] 4F — First Complete Transaction
- [X] 4G — Capability Intelligence
- [X] 4H — Agent + Amazon Bedrock foundation

### Phase 4I — MCP + Deterministic Agent Execution

- [X] 4I-D — Durable Transaction Execution
- [X] 4I-E — Business-Level MCP Execution
- [X] 4I-F — Bounded Transaction Orchestrator
- [X] 4I-G — Agent Runtime
- [X] 4I-H — Transaction Investigation
- [X] 4I-I — Deterministic Multi-Vendor Routing + Recovery Hardening
- [X] 4I-J — Account Context + Policy Guard
- [X] 4I-K — Deterministic Transaction Explainer
- [X] 4I-L — Conversational Request Understanding
- [X] 4I-M — Conversational API Boundary (`POST /api/chat`)

### Phase 4J — Judge-Facing Simulator

- [X] 4J — Judge-Facing Conversational Web Simulator

### Remaining Progression

- [ ] 4K — Alexa+ Integration
- [ ] 4L — Stateful Conversational Context
- [ ] 4M — Scenario Testing + Demo Hardening
- [ ] 4N — Observability + Investigation Enhancements
- [ ] 4O — Submission, Demo and Deployment

> The MCP Streamable HTTP boundary and its business tools are implemented and are the
> backend/agent integration surface. Alexa+ voice integration is **not** implemented;
> it is tracked separately under 4K and must not be claimed unless built.

## Architecture

The current execution architecture follows this principle:

```text
User Request
    ↓
Request Understanding
    ↓
Agent Runtime
    ↓
Planner
    ↓
Capability Validation
    ↓
Account Context + Policy
    ↓
Switcher Routing
    ↓
Controlled Business Tool
    ↓
Vendor Adapter
    ↓
Transaction State Machine
    ↓
Investigation / Recovery
    ↓
AgentResult
    ↓
Transaction Explainer
    ↓
User
```

### Endpoint boundaries

- `POST /api/chat` is the conversational path. It runs the policy-enforced
  `RequestUnderstanding → AgentRuntime → TransactionOrchestrator → MCP` flow shown above.
- `POST /transactions` is a narrow, legacy Vendor A-backed vertical slice. It
  hard-codes Vendor A and executes directly through the persistence service; it does
  **not** enforce the account policy guard and is **not** equivalent to the
  policy-enforced MCP/orchestrator path.
- `planner_candidate_vendor` is advisory only. The deterministic Switcher determines
  the executing vendor; the planner's candidate is not authoritative.
