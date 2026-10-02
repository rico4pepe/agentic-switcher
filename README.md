
# Agentic Switcher

Agentic transaction orchestration and operations platform.

## Overview

Agentic Switcher explores how an AI agent can understand heterogeneous transaction capabilities, construct a safe execution plan, orchestrate transactions through controlled business tools, monitor transaction state, investigate ambiguous outcomes, and explain the result conversationally.

The system is designed around a clear separation of responsibilities:

> The agent reasons about what should happen; deterministic services decide what is allowed to happen; the Switcher executes it; the transaction engine determines what actually happened.

## Current Status

### Phase 4A — Repository + FastAPI

- [X] Python 3.12 environment
- [X] Project virtual environment
- [X] Git repository
- [X] FastAPI application
- [X] Health endpoint
- [X] OpenAPI / Swagger documentation

### Planned Progression

- [ ] 4B — PostgreSQL + SQLAlchemy + Alembic
- [ ] 4C — Domain Models
- [ ] 4D — Transaction State Machine
- [ ] 4E — Vendor Adapters
- [ ] 4F — First Complete Transaction
- [ ] 4G — Capability Intelligence
- [ ] 4H — Agent + Amazon Bedrock
- [ ] 4I — MCP Server
- [ ] 4J — Alexa-style Web Simulator
- [ ] 4K — MCP Apps Investigation / Integration
- [ ] 4L — Stateful Conversational Context
- [ ] 4M — Observability + Investigation
- [ ] 4N — Scenario Testing
- [ ] 4O — Submission, Demo and Deployment

## Development

The project is being developed incrementally using:

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- PostgreSQL
- Amazon Bedrock
- MCP
- React + TypeScript

Each stage is implemented, tested and documented before the project advances to the next stage.
