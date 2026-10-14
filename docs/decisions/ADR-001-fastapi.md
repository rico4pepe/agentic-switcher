# ADR-001: FastAPI Backend Foundation

**Status:** Implemented

## Decision

Use Python 3.12 and FastAPI as the backend and API/orchestration foundation.

## Rationale

FastAPI provides a small typed HTTP boundary for the Switcher while keeping domain and execution services independent of HTTP. Pydantic request validation is used at the API boundary, and business failures remain represented by the canonical transaction state rather than by HTTP-layer control flow.

The implementation now exposes health checking, a narrow Vendor A-backed
`POST /transactions` vertical slice, and the policy-enforced conversational
boundary `POST /api/chat`, alongside the MCP Streamable HTTP business-tool
boundary. It is still not a generic transaction API, and the HTTP layer remains a
thin boundary over the deterministic application services.
