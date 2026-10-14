# Agentic Switcher — Judge-Facing Simulator (Phase 4J / M5)

A responsive, accessible React + TypeScript + Vite application that lets a judge
hold a multi-turn natural-language airtime conversation with the backend —
supplying missing details when asked and explicitly confirming the summarized
purchase — and then inspect the **authoritative** outcome, while also
controlling backend demo scenarios.

The frontend is presentation only. The backend remains authoritative for policy,
vendor routing, execution, and transaction outcomes. The browser can only:

- send `{ "message": "...", "mode": "conversation" }` (plus an opaque
  `conversation_id` to continue an existing conversation) to `POST /api/chat`;
- read and select demo scenarios via `/api/demo/scenarios`.

It never supplies vendor choices, idempotency keys, account balances, or
fabricated statuses, and it never exposes raw MCP or vendor APIs. Confirmation
and cancellation are sent as ordinary conversation turns.

## Prerequisites

- Node.js 20.19+ or 22.12+ (developed against Node 26) and npm.
- The backend running from the repository root on port `8000`, with its
  PostgreSQL database reachable and a populated `.env`. Demo endpoints require
  `DEMO_MODE_ENABLED=true` (the default).

## Local run

From the repository root, start the backend:

```bash
# from /Users/mac/Desktop/agentic-switcher, with the virtualenv active
uvicorn apps.api.app.main:app --reload --port 8000
```

Then start the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

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

| Command             | Purpose                                     |
| ------------------- | ------------------------------------------- |
| `npm run dev`       | Vite dev server with HMR and `/api` proxy   |
| `npm run build`     | Type-check (`tsc -b`) and production bundle |
| `npm run preview`   | Serve the production build locally          |
| `npm run test`      | Run the Vitest + React Testing Library suite |
| `npm run test:watch`| Run the test suite in watch mode            |
| `npm run typecheck` | TypeScript project build only               |
| `npm run lint`      | Oxlint                                       |

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
- **Voice input (disabled)** — a Web Speech API speech-recognition input adapter
  lives in `src/voice/`, but it is turned off for this demo build
  (`VOICE_INPUT_ENABLED = false` in `src/config.ts`), so users type their
  requests. The form shows "Voice input is turned off for this demo." Flipping
  that flag re-enables the input adapter; there is no Alexa+ integration.

Supported scenarios (exact backend enum): `NORMAL`, `VENDOR_A_UNAVAILABLE`,
`POLICY_DENIED`, `TIMEOUT`, `PLANNER_A_A_UNAVAILABLE`.

## Manual verification

With both servers running, at <http://localhost:5173>. Unless a step says
otherwise, submitting the example (`Buy ₦5,000 MTN airtime for 08030000001.`)
reaches a **Confirm purchase** step; click it to execute.

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
5. **Policy denied** — select `POLICY_DENIED`, submit and confirm; the badge
   reads **Policy denied** with reason `Insufficient balance` and no vendor
   reference.
6. **Vendor switch** — select `VENDOR_A_UNAVAILABLE`, submit and confirm; the
   selected vendor is **Vendor B** while the planner candidate is **Vendor A**.
7. **UNKNOWN** — select `TIMEOUT`, submit and confirm; the badge reads
   **Outcome unconfirmed** with neutral styling (never green/success).
8. **Cancel** — at a **Confirm purchase** step, click **Cancel**; the
   conversation ends in a cancelled state and cancellation prevents vendor
   execution (no vendor is ever contacted).
9. **Network error** — stop the backend and submit; confirm the alert heading
   **Backend unreachable** (body: "Could not reach the backend service.").
10. **Scenario independence** — changing the scenario does not submit a
    transaction; changing scenarios updates the "Current scenario" card and the
    header scenario label.

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
