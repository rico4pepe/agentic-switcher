# Agentic Switcher

| Field                     | Details                                        |
| ------------------------- | ---------------------------------------------- |
| **Hackathon**       | Build, Ship, Shape: Amazon Developer Hackathon |
| **Track**           | Alexa+ — self-hosted MCP server path          |
| **Mini challenges** | No mini-challenge claim                        |
| **Demo video**      | [TODO: paste public YouTube link]              |
| **License**         | Apache-2.0                                     |

## For judges: the 60-second version

A customer states what they want — for example, “buy ₦5,000 MTN airtime for 08030000001.” The system gathers any missing details, presents a summary, and requires **explicit confirmation** before execution. The transaction then passes through deterministic, auditable boundaries:

1. The agent proposes a plan; its vendor choice is advisory only.
2. The policy guard decides whether the request is allowed.
3. The Switcher selects the vendor that should execute the request.
4. The transaction state machine records what actually happened.
5. The explanation is derived from that recorded outcome; it never invents success or failure.

The backend exposes this execution boundary through a self-hosted MCP server at `/mcp` using Streamable HTTP. Its three business tools are `find_transaction_capabilities`, `execute_transaction`, and `get_transaction_status` (read-only). The current demo uses deterministic planning and vendor simulators; it does not make a real airtime purchase.

**Try it in about 3 minutes:** follow [Running the demo](#running-the-demo) to start PostgreSQL and both servers, open [http://localhost:5173](http://localhost:5173), enter `Buy ₦5,000 MTN airtime for 08030000001.`, and use the **Demo scenario** panel to try `NORMAL`, `VENDOR_A_UNAVAILABLE`, and `POLICY_DENIED`. Confirm the purchase when prompted, then inspect the MCP activity trace.

## Overview

A financial orchestration platform: agentic transaction orchestration and operations across heterogeneous providers.

**The real-world problem.** In Open Banking and multi-provider payments, a single customer intent — *send money, pay a bill, buy airtime* — can be satisfiable by several providers, each with different capabilities, availability, and policy. A production system needs a layer that routes each transaction to an eligible provider, enforces policy (and, eventually, customer consent) *before* anything executes, explains every outcome truthfully — including ambiguous ones — and meters usage for settlement and billing. Getting this wrong means double-charging a customer or silently sending money to the wrong place.

Agentic Switcher is a working prototype of that orchestration core. It explores how an AI agent can understand heterogeneous transaction capabilities, construct a safe execution plan, orchestrate transactions through controlled business tools, monitor transaction state, investigate ambiguous outcomes, and explain the result conversationally.

The system is designed around a clear separation of responsibilities:

> The agent reasons about what should happen; deterministic application services decide what is allowed to happen; the Switcher determines where the transaction should execute; the vendor executes it; the transaction engine determines what actually happened.

The core product principle is:

> **The user chooses WHAT. The agent understands HOW. The Switcher determines WHERE. The vendor executes. The transaction engine determines WHAT ACTUALLY HAPPENED.**

### Vision, prototype, and future work

- **Vision (not implemented).** A financial orchestration layer for Open Banking-style
  multi-provider payments, where a single intent — send money, pay a bill, buy airtime —
  is routed to an eligible provider, policy and customer consent are enforced before
  execution, outcomes are explained truthfully, and usage is metered for settlement.
- **Prototype (this repository).** The deterministic orchestration core of that vision,
  demonstrated end-to-end for one real use case, **MTN airtime**: request understanding,
  planning, capability validation, policy, Switcher routing, MCP execution,
  transaction-state handling, investigation, and explanation. The vendors are
  deterministic in-memory simulators, not real integrations.
- **Future work.** Real provider integrations, additional networks and products
  (money transfer, bill payment), consent capture, usage metering, postpaid policy,
  cross-process conversation state, and Alexa+-style voice. See "Optional future work"
  and "Not implemented" below.

## Current Status

Everything in this section is checked against the code and the latest recorded
verification (2026-10-16:  495 backend tests and 169 frontend tests across 13 test
files passing, with the frontend lint, typecheck, and production build passing).
The full backend suite requires the Compose PostgreSQL service to be running.

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
  execution path. Confirmation and cancellation are sent only as an explicit,
  button-driven `action` (`confirm`/`cancel`), which is mutually exclusive with a
  free-text `message`, so a typed "yes" or "cancel" can never execute or cancel a
  transaction. Conversation state is single-process and in-memory (not
  persisted); `UNKNOWN` outcomes are never retried and are reported truthfully.
  Transaction outcomes themselves are persisted in PostgreSQL.
- [X] **MCP activity instrumentation** — every `POST /api/chat` response includes
  the real MCP tool calls made while producing it (`mcp_events` on
  `ChatResponse`), so the UI can show an evidence-backed call trace. Only actual
  `tools/call` invocations are recorded (never a registered-but-unused tool);
  values are sanitized at the MCP boundary (credentials and idempotency keys
  redacted, phone numbers masked); and recorded events are carried on execution
  errors too, so an `UNKNOWN` result still shows what actually happened. See
  `agent/orchestrator/mcp_events.py`.

### Optional future work

- [ ] Persist conversation state and support cross-process conversations.
- [ ] Postpaid credit-limit policy (postpaid requests are currently denied
  because no postpaid rule set exists).
- [ ] Drive `UNKNOWN` investigation/recovery from the conversational flow.
- [ ] Live account administration and additional vendor workflow shapes.
- [ ] Observability and investigation enhancements.
- [ ] Deployment and operational hardening.

### Voice and conversational experience

- [X] **Voice output** — the frontend can speak the assistant's authoritative
  responses through the browser Speech Synthesis API ("Text + spoken" mode).
  Speech is derived from the backend response and changes no backend contract;
  the text transcript remains authoritative.
- [ ] **Voice input (built, disabled)** — a browser speech-recognition input
  adapter is implemented under `frontend/src/voice/` but is turned off for this
  demo build (`VOICE_INPUT_ENABLED = false` in `frontend/src/config.ts`), so
  users cannot speak directly to the agent and type their requests instead. It
  can be re-enabled by flipping that flag. The reasoning is recorded in
  `docs/feedback/amazon-friction-log.md`.
- [ ] **Alexa+-style simulation / integration** — a planned milestone and
  **not** built.

### Not implemented

- [ ] **Real vendor/network execution** — the Vendor A and Vendor B adapters are
  deterministic in-memory simulators; no real transactions are sent. Only the
  adapters are simulated: transaction records are still persisted in PostgreSQL.
- [ ] **Networks other than MTN** — no Glo, Airtel, or 9mobile support.
- [ ] **Money transfer and bill payment** — only airtime purchase is implemented;
  sending money and paying bills are meaningful target use cases the architecture
  is built to serve, not current features.

> The MCP Streamable HTTP boundary and its business tools are implemented and are
> the backend/agent integration surface. Voice output is implemented; voice input
> is built but disabled. Alexa+-style integration is **not** implemented and must
> not be claimed unless built.

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

- `POST /api/chat` is the only supported transaction-execution HTTP path. It runs
  the policy-enforced `RequestUnderstanding → AgentRuntime → TransactionOrchestrator → MCP`
  flow shown above.
- A legacy Vendor A-only `POST /transactions` endpoint existed in early
  milestones. It hard-coded Vendor A and executed directly through the
  persistence service without enforcing the account policy guard, so it has been
  retired; the policy-enforced `/api/chat`/MCP path is now the only
  transaction-execution path.
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
- OpenAPI / Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs).
- MCP Streamable HTTP is mounted at [http://localhost:8000/mcp](http://localhost:8000/mcp).

### 6. Install frontend dependencies and start Vite

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/api/*` to the backend on port 8000
(see `frontend/vite.config.ts`), so no backend CORS configuration is needed.

### Local URLs

| Service            | URL                                                         |
| ------------------ | ----------------------------------------------------------- |
| Frontend (Vite)    | [http://localhost:5173](http://localhost:5173)               |
| Backend health     | [http://localhost:8000/health](http://localhost:8000/health) |
| Backend API / docs | [http://localhost:8000/docs](http://localhost:8000/docs)     |
| MCP endpoint       | [http://localhost:8000/mcp](http://localhost:8000/mcp)       |
| PostgreSQL         | `localhost:5432`, database `agentic_switcher`           |

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

## Verify the MCP interface

The backend exposes an MCP server over the **Streamable HTTP** transport at
[http://localhost:8000/mcp](http://localhost:8000/mcp) (mounted in `apps/api/app/main.py`; server in
`apps/api/app/mcp_server/app.py`). It uses the official MCP Python SDK
(`mcp>=2,<3`; `mcp` / `mcp-types` package version **2.3.0**) and exposes exactly
three business tools: `find_transaction_capabilities`, `execute_transaction`,
and `get_transaction_status`. Verification needs the backend, PostgreSQL, and the
applied migrations from the steps above.

### Protocol revision (verified 2026-10-14)

The SDK **package version** (`mcp` 2.3.0) is distinct from the MCP
**specification revision**, which is a `YYYY-MM-DD` date that marks the last
backwards-incompatible protocol change. The server supports multiple revisions,
and the one that is negotiated depends on the client:

- **MCP Inspector CLI** (`@modelcontextprotocol/inspector@2.11.0`) negotiated
  **`2025-11-25`** — the newest handshake-era revision — through the `initialize`
  handshake.
- **Official Python SDK** (`mcp` 2.3.0): the high-level `Client` in its default
  `mode="auto"` sends a `server/discover` probe and negotiated the modern
  revision **`2026-07-28`**. A low-level
  `mcp.client.streamable_http.streamable_http_client` + `ClientSession` performs
  the handshake instead and negotiated **`2025-11-25`**.
- Offering older revisions to the `initialize` handshake shows the server also
  negotiates **`2024-11-05`**, **`2025-03-26`**, and **`2025-06-18`** when a
  client asks for them, and falls back to `2025-11-25` for unrecognized or newer
  handshake offers. The modern `server/discover` probe reports
  `supportedVersions: ["2026-07-28"]`.

So the server is not limited to one revision: over the same Streamable HTTP
endpoint it serves the handshake era (`2024-11-05` through `2025-11-25`) and the
modern era (`2026-07-28`).

### MCP Inspector (no code)

```bash
# tools/list — discovery and input schemas
npx -y @modelcontextprotocol/inspector@latest --cli \
  --server-url http://localhost:8000/mcp --method tools/list

# call a read-only tool
npx -y @modelcontextprotocol/inspector@latest --cli \
  --server-url http://localhost:8000/mcp --method tools/call \
  --tool-name find_transaction_capabilities \
  --tool-arg service_type=airtime product_type=airtime network=MTN
```

Expected: `tools/list` reports exactly the three tools above; the call returns
`isError: false` with `vendor_a` and `vendor_b` MTN airtime capabilities. The
Inspector web UI (run `npx -y @modelcontextprotocol/inspector@latest`, then connect
to `http://localhost:8000/mcp`) works the same way because its local proxy connects
server-side.

A standard MCP client connects over Streamable HTTP, so the official Python SDK
works too. A low-level `mcp.client.streamable_http.streamable_http_client` +
`ClientSession` negotiates the legacy handshake (`initialize` → `tools/list` →
`tools/call`); the high-level `Client` negotiates the modern `server/discover`
probe instead (see "Protocol revision" above).

### Transport security (Host and Origin)

The server enables DNS-rebinding protection with an explicit allow-list
(`create_mcp_server` in `apps/api/app/mcp_server/app.py`):

- **Host** must be `localhost` or `127.0.0.1` (any port). Any other `Host` is
  rejected with `421 Invalid Host header`; connect via `http://localhost:8000/mcp`
  or `http://127.0.0.1:8000/mcp`.
- **Origin** must be absent or allow-listed; the allow-list is currently empty, so
  any request carrying a browser `Origin` header is rejected with
  `403 Invalid Origin header`. Server-side MCP clients (SDK, Inspector CLI/proxy)
  send no `Origin`; a browser page calling the endpoint cross-origin would.
- `POST /mcp` redirects (`307`) to `POST /mcp/`. Standard clients follow it; you may
  also target `http://localhost:8000/mcp/` directly.

### What a successful call does and does not prove

A successful (`200`) tool call proves the MCP boundary is reachable and the tool
ran. It does **not** by itself prove the policy guard cannot be bypassed. Policy
enforcement is proven by the boundary tests: `tests/integration/test_mcp_tool_boundary.py`
(only declared inputs are accepted; injected vendor fields cannot influence routing;
internal vendor operations are not callable) and
`tests/integration/test_mcp_execution.py::test_mcp_policy_denial_is_structured_and_stops_direct_execution`
(a denied `execute_transaction` returns `status: "denied"` and performs no capability
lookup or vendor submission). Observe the denial directly:

```bash
npx -y @modelcontextprotocol/inspector@latest --cli \
  --server-url http://localhost:8000/mcp --method tools/call \
  --tool-name execute_transaction \
  --tool-arg service_type=airtime product_type=airtime network=MTN \
  --tool-arg beneficiary=08030000001 amount=999999.00 \
  --tool-arg idempotency_key=readme-demo-001
```

Expected: `isError: false` with `status: "denied"`, `action: "deny"`, `reason: "Insufficient balance"`, and `transaction_id: null` (the demo balance is `10000`);
no vendor is called.

Run the MCP tests directly (needs PostgreSQL):

```bash
python -m pytest tests/integration/test_mcp_mount.py \
  tests/integration/test_mcp_capabilities.py \
  tests/integration/test_mcp_execution.py \
  tests/integration/test_mcp_tool_boundary.py
```

The MCP interface is the backend/agent integration surface. It is **not** an LLM and
is **not** Alexa+ integration: Alexa+-style integration is a planned milestone and
is not implemented.

## Project documentation

- [`docs/architecture/overview.md`](docs/architecture/overview.md) — implemented
  foundation, boundaries, and intended complete architecture.
- [`docs/engineering/challenges-and-decisions.md`](docs/engineering/challenges-and-decisions.md)
  — the hard engineering problems (policy bypass, deterministic routing, truthful
  outcomes, idempotency, concurrency, observability) and how each was resolved.
- [`docs/decisions/`](docs/decisions/) — Architecture Decision Records
  (ADR-001 … ADR-007).
- [`docs/scenarios/transaction-scenarios.md`](docs/scenarios/transaction-scenarios.md)
  — expected behavior, status, and boundaries per transaction scenario.
- [`docs/feedback/`](docs/feedback/) — Amazon/MCP tool feedback and the voice-input
  friction log.

## Devpost submission draft

> **Agentic Switcher** is a working prototype of the orchestration layer that
> Open Banking and multi-provider payments require. In that world, a single
> customer intent — *send money, pay a bill, buy airtime* — can be served by
> several providers, and a production system needs a layer that routes each
> transaction to an eligible provider, enforces policy and customer consent
> *before* anything executes, explains every outcome truthfully (including
> ambiguous ones), and meters usage for settlement and billing. Agentic Switcher
> demonstrates the orchestration core of that layer — deterministic routing,
> policy enforcement, and truthful outcome reporting — for one real use case,
> **MTN airtime**: a user states what they want in natural language and a bounded
> agent turns that into a safe, policy-checked transaction that executes through
> controlled vendor adapters. The architecture separates reasoning from
> execution: the agent layer proposes *what* should happen, deterministic
> application services decide what is *allowed* to happen, a Switcher decides
> *where* the transaction executes, and the transaction engine records *what
> actually happened* — including truthful handling of ambiguous outcomes. No real
> provider, network, or financial transaction is executed: the vendors are
> deterministic in-memory simulators (see "Honest scope" below).

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
- Ships a presentation-only web demo with bounded, deterministic scenarios judges
  can drive (normal, vendor unavailable, policy denied, timeout, planner preference
  overridden).

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
migrations. The integration surface is a **self-hosted MCP server over the
Streamable HTTP transport** — served at `/mcp` on the same FastAPI app via the
official `mcp` Python SDK 2.3.0 — exposing `find_transaction_capabilities`,
`execute_transaction`, and the read-only `get_transaction_status`. It supports
multiple MCP protocol revisions: the MCP Inspector CLI and the low-level SDK
`ClientSession` negotiated the handshake-era revision `2025-11-25`, while the
SDK's high-level `Client` negotiated the modern revision `2026-07-28`
(verified 2026-10-14; see "Verify the MCP interface" above). The frontend is
React 19 + TypeScript + Vite and is presentation-only. See
`docs/architecture/overview.md` for the full overview.

**Where the LLM fits.** The planner boundary is defined by an `LLMProvider`
contract. The running demo wires a `DeterministicPlannerProvider` into that
boundary, so the demo performs no model inference: request understanding,
planning, policy, routing, investigation, and explanation are deterministic. A
`BedrockProvider` (Amazon Bedrock Converse) implements the same contract and is
covered by unit tests, but it is not wired into the demo path and requires
`BEDROCK_MODEL_ID` to be configured. No LLM-based planning or understanding is
used by the demo.

**Honest scope**

- Vendor A and Vendor B are deterministic in-memory **simulators**, not real
  integrations. **No production Nigerian bank, open-banking, or payment API is
  integrated**: the Open Banking framing is the thesis the architecture is built
  to serve, and the demo executes no real vendor, network, or financial
  transaction. Vendor adapters sit behind a stable interface, so a real provider
  would replace a simulator without changing the agent, policy, routing, or
  explanation layers. Transaction records are nevertheless persisted in
  PostgreSQL.
- Request understanding, planning, policy, routing, investigation, and
  explanation are deterministic. No LLM is called on the demo request path; the
  Bedrock Converse provider exists behind the `LLMProvider` contract but is not
  wired in.
- Only MTN airtime is supported.
- Voice output is implemented (browser Speech Synthesis, derived from the
  authoritative backend response). Voice input is implemented but disabled for
  the demo build. Alexa+-style integration is a planned milestone and is **not**
  implemented.
- Conversation state is single-process and in-memory, so it does not survive a
  restart or span multiple processes. This is separate from transaction
  persistence, which is durable in PostgreSQL.
- **Transaction state, `UNKNOWN`, and idempotency.** Transaction state is tracked
  by an explicit state machine (ADR-002) with a durable `SUBMITTING` boundary
  written before any vendor submission. If a submission is ambiguous (for example
  a vendor timeout), the transaction is recorded as `UNKNOWN` — **not** `FAILED` —
  because failure cannot be proven, and an `UNKNOWN` transaction is never
  automatically retried and never reported as a success (ADR-003). Idempotency is
  scoped to a caller-supplied key: replaying a request with the same key and the
  same business inputs resumes the existing transaction instead of resubmitting,
  and a database uniqueness constraint backstops duplicate records. The
  conversational path generates a **new** idempotency key per request, so
  re-stating the same intent as a fresh request is **not** deduplicated across
  requests. This is not a universal exactly-once guarantee.
- **Customer consent capture and usage metering are not implemented.** They are
  part of the Open Banking thesis and the target the architecture is built
  toward, not features of the current demo.

**Submission track:** **Alexa+ track**, using the self-hosted MCP server path (Streamable HTTP; the `2025-11-25` handshake revision was verified with MCP Inspector and the low-level SDK client). No Alexa+ voice integration is claimed. Voice output is available through browser speech synthesis; voice input is disabled for this demo.
