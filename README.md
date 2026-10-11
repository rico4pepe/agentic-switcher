# Agentic Switcher

Agentic transaction orchestration and operations platform.

## Overview

Agentic Switcher explores how an AI agent can understand heterogeneous transaction capabilities, construct a safe execution plan, orchestrate transactions through controlled business tools, monitor transaction state, investigate ambiguous outcomes, and explain the result conversationally.

The system is designed around a clear separation of responsibilities:

> The agent reasons about what should happen; deterministic application services decide what is allowed to happen; the Switcher determines where the transaction should execute; the vendor executes it; the transaction engine determines what actually happened.

The core product principle is:

> **The user chooses WHAT. The agent understands HOW. The Switcher determines WHERE. The vendor executes. The transaction engine determines WHAT ACTUALLY HAPPENED.**

## Current Status

Everything in this section is checked against the code and the latest recorded
verification (2026-10-11: 330 backend tests and 63 frontend tests passing, with
the frontend lint, typecheck, and production build passing).

Vendor A and Vendor B are **deterministic in-memory simulators**: no real vendor,
network, or financial execution occurs. That is a property of the vendor adapters
and of the in-memory conversation state, not of the application as a whole.
Application transaction records and the vendor simulator operation ledgers are
persisted in PostgreSQL via SQLAlchemy and Alembic.

### Historical Foundation — Repository + FastAPI (Phase 4A)

This is the original scaffold, retained as historical context. It predates the
current milestone progression and does not represent the current feature set.

- [X] Python 3.12 environment
- [X] Project virtual environment
- [X] Git repository
- [X] FastAPI application
- [X] Health endpoint
- [X] OpenAPI / Swagger documentation

### Implemented and verified

- [X] **Phase 4B–4H — Core platform foundation**: PostgreSQL + SQLAlchemy +
  Alembic; domain models; transaction state machine; vendor adapters; first
  complete transaction; capability intelligence; and the agent + Amazon Bedrock
  foundation (`LLMProvider` contract with a Bedrock Converse provider).
- [X] **Phase 4I — MCP + deterministic agent execution**: durable transaction
  execution; business-level MCP execution; bounded transaction orchestrator;
  agent runtime; transaction investigation; deterministic multi-vendor routing +
  recovery hardening; account context + policy guard; deterministic transaction
  explainer; conversational request understanding; and the conversational API
  boundary (`POST /api/chat`).
- [X] **Phase 4J — Judge-facing simulator**: a presentation-only React +
  TypeScript + Vite web app plus the bounded server-side demo scenario API.
- [X] **Multi-turn airtime conversation** (`docs/decisions/ADR-007-conversation-boundary.md`):
  `POST /api/chat` with `mode="conversation"` collects missing fields, requires
  explicit confirmation, and then dispatches through the single existing
  execution path. Conversation state is single-process and in-memory (not
  persisted); `UNKNOWN` outcomes are never retried and are reported truthfully.
  Transaction outcomes themselves are persisted in PostgreSQL.

### Optional future work

- [ ] Persist conversation state and support cross-process conversations.
- [ ] Postpaid credit-limit policy (postpaid requests are currently denied
  because no postpaid rule set exists).
- [ ] Drive `UNKNOWN` investigation/recovery from the conversational flow.
- [ ] Live account administration and additional vendor workflow shapes.
- [ ] Observability and investigation enhancements.
- [ ] Deployment and operational hardening.

### Not implemented

- [ ] **Alexa+ integration and voice I/O** — tracked separately and **not**
  built.
- [ ] **Real vendor/network execution** — the Vendor A and Vendor B adapters are
  deterministic in-memory simulators; no real transactions are sent. Only the
  adapters are simulated: transaction records are still persisted in PostgreSQL.
- [ ] **Networks other than MTN** — no Glo, Airtel, or 9mobile support.

> The MCP Streamable HTTP boundary and its business tools are implemented and are
> the backend/agent integration surface. Alexa+ voice integration is **not**
> implemented and must not be claimed unless built.

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

## Running the demo

The demo runs three local processes: PostgreSQL (Docker Compose), the FastAPI
backend, and the Vite dev server. Run commands from the repository root unless a
step says otherwise.

### Requirements

- **Python 3.12** — the backend is developed and tested on Python 3.12. There is
  no pinned minimum in `apps/api/requirements.txt` (only `mcp>=2,<3` bounds a
  version).
- **Node.js 20.19+ or 22.12+** (developed against Node 26) and npm — required by
  Vite 8 in `frontend/package.json`.
- **Docker** with the Compose plugin — for the PostgreSQL service defined in
  `docker-compose.yml`.

### 1. Create the virtual environment and install backend dependencies

```bash
python3.12 -m venv .venv        # or your Python 3.12 interpreter
source .venv/bin/activate
pip install -r apps/api/requirements.txt
```

### 2. Configure the environment

```bash
cp .env.example .env
```

The backend loads `.env` from the repository root (see
`apps/api/app/config.py`). `DATABASE_URL` is required; the other values in
`.env.example` are demo defaults and may be left unchanged.

- `DATABASE_URL` — points at the Compose PostgreSQL service
  (`postgresql+psycopg://agentic:agentic_dev@localhost:5432/agentic_switcher`,
  matching `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` in
  `docker-compose.yml`).
- `VENDOR_A_API_KEY` — placeholder used by the deterministic simulator.
- `DEMO_ACCOUNT_BENEFICIARY`, `DEMO_ACCOUNT_TYPE`, `DEMO_ACCOUNT_BALANCE` —
  demo account context.

The demo scenario endpoints are enabled by default (`DEMO_MODE_ENABLED=true`,
defaulted in `apps/api/app/config.py`; it is not required in `.env`).

### 3. Start PostgreSQL

```bash
docker compose up -d postgres
```

Wait until PostgreSQL accepts connections before migrating:

```bash
until docker compose exec -T postgres pg_isready -U agentic >/dev/null 2>&1; do sleep 1; done
```

### 4. Apply database migrations

```bash
# run from the repository root, with the virtualenv active
alembic upgrade head
```

`alembic.ini` sets `script_location` to `database/migrations` (four revisions;
head `9f1d6b2a9fe1`) and gets its URL from `settings.database_url` in
`database/migrations/env.py`. Migrations are additive and do not reset data.

### 5. Start the backend

```bash
uvicorn apps.api.app.main:app --reload --port 8000
```

- Health check: `curl http://localhost:8000/health` returns
  `{"status":"ok","service":"agentic-switcher-api"}`.
- OpenAPI / Swagger UI: <http://localhost:8000/docs>.
- MCP Streamable HTTP is mounted at <http://localhost:8000/mcp>.

### 6. Install frontend dependencies and start Vite

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the backend on port 8000
(see `frontend/vite.config.ts`), so no backend CORS configuration is needed.

### Local URLs

| Service            | URL                                                |
| ------------------ | -------------------------------------------------- |
| Frontend (Vite)    | <http://localhost:5173>                            |
| Backend health     | <http://localhost:8000/health>                     |
| Backend API / docs | <http://localhost:8000/docs>                       |
| MCP endpoint       | <http://localhost:8000/mcp>                        |
| PostgreSQL         | `localhost:5432`, database `agentic_switcher`      |

### Running the tests

```bash
# backend, from the repository root with the virtualenv active
python -m pytest

# frontend
cd frontend
npm run test
npm run lint
npm run typecheck
npm run build
```

## Devpost submission draft

> **Agentic Switcher** is a demo of agentic transaction orchestration: a user
> states what they want in natural language, and a bounded agent turns that into
> a safe, policy-checked airtime purchase that executes through controlled vendor
> adapters. The architecture separates reasoning from execution: the agent layer
> proposes *what* should happen, deterministic application services decide what
> is *allowed* to happen, a Switcher decides *where* the transaction executes,
> and the transaction engine records *what actually happened* — including
> truthful handling of ambiguous outcomes.

**What it does**

- Accepts a natural-language airtime request and either executes it immediately
  or drives a multi-turn conversation that collects missing details and requires
  explicit confirmation before executing once.
- Validates the request against a capability registry, applies a deterministic
  account/policy guard, routes to an eligible vendor, and executes through a
  controlled business tool.
- Reports the authoritative result plus a deterministic explanation, and never
  fabricates success or failure. An ambiguous vendor result is surfaced as
  `UNKNOWN`, not as `FAILED`, and is never automatically retried.
- Ships a presentation-only React simulator for judges, with bounded demo
  scenarios (normal, vendor unavailable, policy denied, timeout, planner
  preference overridden).

**How it is built (architecture summary)**

```text
User message
  → RequestUnderstanding (deterministic parser)
  → AgentRuntime
  → ExecutionPlanPlanner (deterministic provider; no LLM call)
  → Capability validation (deterministic)
  → Account context + policy guard (deterministic)
  → Deterministic Switcher routing
  → MCP business tool
  → Vendor adapter (deterministic in-memory simulator)
  → Transaction state machine (PostgreSQL persistence)
  → Investigation / recovery
  → AgentResult
  → TransactionExplainer (deterministic)
  → User
```

The backend is Python 3.12 + FastAPI with PostgreSQL, SQLAlchemy, and Alembic
migrations. The integration surface is an MCP Streamable HTTP server exposing
`find_transaction_capabilities`, `execute_transaction`, and the read-only
`get_transaction_status`. The frontend is React 19 + TypeScript + Vite and is
presentation-only. See `docs/architecture/overview.md` for the full overview.

**Where the LLM fits.** The planner boundary is defined by an `LLMProvider`
contract. The running demo wires a `DeterministicPlannerProvider` into that
boundary, so the demo performs no model inference: request understanding,
planning, policy, routing, investigation, and explanation are deterministic. A
`BedrockProvider` (Amazon Bedrock Converse) implements the same contract and is
covered by unit tests, but it is not wired into the demo path and requires
`BEDROCK_MODEL_ID` to be configured. No LLM-based planning or understanding is
used by the demo.

**Honest scope**

- The Vendor A and Vendor B adapters are deterministic in-memory **simulators**;
  no real vendor, network, or financial execution occurs. Transaction records are
  nevertheless persisted in PostgreSQL.
- Request understanding, planning, policy, routing, investigation, and
  explanation are deterministic. No LLM is called on the demo request path; the
  Bedrock Converse provider exists behind the `LLMProvider` contract but is not
  wired in.
- Only MTN airtime is supported.
- Alexa+ integration and voice I/O are **not** implemented.
- Conversation state is single-process and in-memory, so it does not survive a
  restart or span multiple processes. This is separate from transaction
  persistence, which is durable in PostgreSQL.
