
# Agentic Switcher — Judge-Facing Simulator (Phase 4J / M5)

A responsive, accessible React + TypeScript + Vite application that lets a judge
hold a multi-turn natural-language airtime conversation with the backend —
supplying missing details when asked and explicitly confirming the summarized
purchase — and then inspect the **authoritative** outcome, while also
controlling backend demo scenarios.

## For judges in a hurry

1. Start PostgreSQL and the backend, then start the frontend (see [Local run](#local-run)).
2. Open [http://localhost:5173](http://localhost:5173).
3. Run these three core scenarios:
   - `NORMAL` — complete a simulated successful airtime purchase.
   - `VENDOR_A_UNAVAILABLE` — see the Switcher select Vendor B when the planner candidate is Vendor A.
   - `POLICY_DENIED` — see the policy guard deny the request before vendor execution.
4. After each turn, inspect the **MCP activity** panel. It shows the actual backend MCP tool calls returned for that turn.

All outcomes are simulated; no real airtime purchase is made.

The frontend is presentation only. The backend remains authoritative for policy,
vendor routing, execution, and transaction outcomes. The browser can only:

- send `{ "message": "...", "mode": "conversation" }` (plus an opaque
  `conversation_id` to continue an existing conversation) to `POST /api/chat`;
- send an explicit, button-only control action to `POST /api/chat` —
  `{ "action": "confirm" | "cancel", "conversation_id": "...", "mode": "conversation" }`;
- read and select demo scenarios via `/api/demo/scenarios`.

It never supplies vendor choices, idempotency keys, account balances, or
fabricated statuses, and it never exposes raw MCP or vendor APIs. Confirmation and
cancellation are **never** inferred from typed free text: the `action` field is
mutually exclusive with `message`, and the backend validates the action against
the conversation's actual state, so a typed "yes" or "cancel" can never execute or
cancel a transaction. The browser renders the `mcp_events` the backend returns on
each chat response as a read-only MCP activity trace; it cannot call MCP or a
vendor directly.

## Prerequisites

- Node.js 20.19+ or 22.12+ (developed against Node 26) and npm.
- The backend running from the repository root on port `8000`, with its
  PostgreSQL database reachable and a populated `.env`. Demo endpoints require
  `DEMO_MODE_ENABLED=true` (the default).

## Local run

From the repository root, start the backend:

```bash
# from the repository root, with the virtualenv active
uvicorn apps.api.app.main:app --reload --port 8000
```

Then start the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## API proxy / base URL configuration

In development, Vite proxies `/api/*` to `http://localhost:8000` (see
`vite.config.ts`). The browser therefore only ever talks to the Vite origin, so
no backend CORS changes are required.

If the app is served from a different origin than the backend (for example a
static `dist/` build), set `VITE_API_BASE_URL` before building/serving:

```bash
# frontend/.env.local
VITE_API_BASE_URL=https://my-backend.example.com
```

The value is prefixed to every request path. When it is empty (the default), the
app issues relative `/api/...` requests and relies on the proxy or a same-origin
deployment.

## Scripts

| Command                | Purpose                                       |
| ---------------------- | --------------------------------------------- |
| `npm run dev`        | Vite dev server with HMR and `/api` proxy   |
| `npm run build`      | Type-check (`tsc -b`) and production bundle |
| `npm run preview`    | Serve the production build locally            |
| `npm run test`       | Run the Vitest + React Testing Library suite  |
| `npm run test:watch` | Run the test suite in watch mode              |
| `npm run typecheck`  | TypeScript project build only                 |
| `npm run lint`       | Oxlint                                        |

## What the UI does

- **Transaction request** — a natural-language input with a usable example
  (`Buy ₦5,000 MTN airtime for 08030000001.`). Submission is disabled while the
  input is empty/whitespace, while a request is in flight, or once a conversation
  is terminal.
- **Multi-turn conversation** — a transcript of user and assistant turns. The
  backend returns one of four steps: `clarify` (asks for missing details and
  lists them), `confirm` (a summary of amount, network, and beneficiary with
  **Confirm purchase** / **Cancel**), `complete` (the authoritative outcome), or
  `cancelled`. A terminal conversation offers **Start a new conversation** and
  disables further input.
- **Result panel** — renders the actual `POST /api/chat` response: status,
  transaction ID, service/product, amount, network, beneficiary, selected
  vendor, planner candidate, action, reason, message, vendor reference, and the
  deterministic explanation. A collapsible raw JSON block is included for
  transparency.
- **MCP activity panel** — a read-only trace of the *actual* MCP tool calls the
  backend made for the current turn (from `mcp_events` on the chat response),
  each with its tool name, status (`succeeded`/`failed`), and a short recorded
  result. It shows what really ran, not a scripted or scenario-derived list. A
  turn with no MCP call shows an empty state. Values are sanitized by the backend
  before they reach the browser, so the panel never shows credentials or
  idempotency keys and masks personal identifiers.
- **Explicit states** — empty, loading, validation error (HTTP 400/422),
  network error, and the result outcomes: success, failed, policy-denied, and
  UNKNOWN.
- **UNKNOWN safety** — an `unknown` status is always labeled **"Outcome
  unconfirmed"** and rendered with neutral styling. It never uses success
  styling or success wording, and the UI never assumes success or failure.
- **Demo scenario controls** — reads `GET /api/demo/scenarios`, arms a scenario
  with `POST /api/demo/scenarios`, and restores normal conditions with
  `POST /api/demo/scenarios/reset`. Selecting a scenario configures backend
  conditions **independently** of transaction submission and never executes a
  transaction. The current scenario and its description are always displayed.
- **Voice output** — when the browser supports the Web Speech API Speech
  Synthesis, the assistant's authoritative response can be spoken. A header
  control switches between **Text only** and **Text + spoken**; speech is derived
  from the backend response and the text transcript remains authoritative. Voice
  output never changes policy, routing, execution, or confirmation.
  Supported scenarios (exact backend enum): `NORMAL`, `VENDOR_A_UNAVAILABLE`,
  `POLICY_DENIED`, `TIMEOUT`, `PLANNER_A_A_UNAVAILABLE`.

## Limitations

- **Presentation only.** The app holds no policy, routing, or transaction logic
  and cannot execute anything on its own; the backend is authoritative for every
  outcome.
- **Voice input is disabled** (`VOICE_INPUT_ENABLED = false` in `src/config.ts`).
  The Web Speech API recognition adapter exists under `src/voice/`, but the demo
  accepts typed requests only and the form shows “Voice input is turned off for
  this demo. Type your request in the box above.” Voice **output** (browser Speech
  Synthesis over the authoritative response) is enabled. There is no Alexa+
  integration.
- **Simulated outcomes.** Vendor success, failure, and timeouts are produced by
  deterministic backend simulators; no real airtime purchase is made.
- **Conversation state is backend-side, single-process, and in-memory.** It does
  not survive a backend restart; the UI keeps only the current `conversation_id`.
- **`UNKNOWN` is never shown as success or failure.** An unconfirmed outcome is
  labeled "Outcome unconfirmed" with neutral styling (see ADR-003 in the root
  [`docs/decisions/`](../docs/decisions/) and the
  [engineering challenges doc](../docs/engineering/challenges-and-decisions.md)).

## Manual verification

With both servers running, open [http://localhost:5173](http://localhost:5173). Unless a step says
otherwise, submitting the example (`Buy ₦5,000 MTN airtime for 08030000001.`)
reaches a **Confirm purchase** step; click it to execute.

### Core flow (steps 1–4)

1. **Health** — confirm the backend is reachable (`curl localhost:8000/health`
   returns `{"status":"ok",...}`).
2. **Empty input** — the Submit button stays disabled until you type a request.
3. **Clarify** — submit a partial request such as `Buy airtime`; the assistant
   asks for the missing details and shows no result.
4. **Simulated success** — keep scenario `NORMAL`, submit the example, review the
   summary, and click **Confirm purchase**. The badge reads **Success**, the
   transaction ID/vendor reference are populated, and the explanation matches.
   This is a simulated success produced by the deterministic vendor simulator;
   no real airtime purchase is made.

### Failure paths (steps 5–7)

5. **Policy denied** — select `POLICY_DENIED`, submit and confirm; the badge
   reads **Policy denied** with reason `Insufficient balance` and no vendor
   reference.
6. **Vendor switch** — select `VENDOR_A_UNAVAILABLE`, submit and confirm; the
   selected vendor is **Vendor B** while the planner candidate is **Vendor A**.
7. **UNKNOWN** — select `TIMEOUT`, submit and confirm; the badge reads
   **Outcome unconfirmed** with neutral styling (never green/success).

### Edge cases (steps 8–11)

8. **Cancel** — at a **Confirm purchase** step, click **Cancel**; the
   conversation ends in a cancelled state and cancellation prevents vendor
   execution (no vendor is ever contacted).
9. **Network error** — stop the backend and submit; confirm the alert heading
   **Backend unreachable** (body: “Could not reach the backend service.”).
10. **Scenario independence** — changing the scenario does not submit a
    transaction; changing scenarios updates the “Current scenario” card and the
    header scenario label.
11. **MCP activity trace** — before any request, the **MCP activity** panel shows
    an empty state. After confirming a transaction, it lists the real tool calls
    made for that turn (capability discovery, execution, and any status lookup)
    with their status; the trace reflects what actually ran, not the scenario
    label. A policy-denied turn still shows capability discovery but no execution
    call.

## Testing

Frontend (Vitest + jsdom + React Testing Library):

```bash
cd frontend
npm run test
npm run build
```

Backend (from the repository root, with the virtualenv active):

```bash
python -m pytest tests/ -xvs
```
