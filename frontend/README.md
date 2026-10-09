# Agentic Switcher — Judge-Facing Simulator (Phase 4J / M5)

A responsive, accessible React + TypeScript + Vite application that lets a judge
submit a natural-language transaction request and inspect the **authoritative**
backend outcome, while also controlling backend demo scenarios.

The frontend is presentation only. The backend remains authoritative for policy,
vendor routing, execution, and transaction outcomes. The browser can only:

- send `{ "message": "..." }` to `POST /api/chat`;
- read and select demo scenarios via `/api/demo/scenarios`.

It never supplies vendor choices, idempotency keys, account balances, or
fabricated statuses, and it never exposes raw MCP or vendor APIs.

## Prerequisites

- Node.js 20+ (developed against Node 26) and npm.
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
  input is empty/whitespace or while a request is in flight.
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

Supported scenarios (exact backend enum): `NORMAL`, `VENDOR_A_UNAVAILABLE`,
`POLICY_DENIED`, `TIMEOUT`, `PLANNER_A_A_UNAVAILABLE`.

## Manual verification

With both servers running, at <http://localhost:5173>:

1. **Health** — confirm the backend is reachable (`curl localhost:8000/health`
   returns `{"status":"ok",...}`).
2. **Empty input** — the Submit button stays disabled until you type a request.
3. **Success** — keep scenario `NORMAL`, submit the example, and confirm the
   badge reads **Success**, the transaction ID/vendor reference are populated,
   and the explanation matches.
4. **Policy denied** — select `POLICY_DENIED`, submit the example, and confirm
   the badge reads **Policy denied** with reason `Insufficient balance` and no
   vendor reference.
5. **Vendor switch** — select `VENDOR_A_UNAVAILABLE`, submit, and confirm the
   selected vendor is **Vendor B** while the planner candidate is **Vendor A**.
6. **UNKNOWN** — select `TIMEOUT`, submit, and confirm the badge reads
   **Outcome unconfirmed** with neutral styling (never green/success).
7. **Validation error** — submit `hello there` and confirm a
   "Request could not be accepted" message (HTTP 400), with no result panel.
8. **Network error** — stop the backend and submit; confirm a "Backend
   unreachable" message.
9. **Scenario independence** — changing the scenario does not submit a
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
