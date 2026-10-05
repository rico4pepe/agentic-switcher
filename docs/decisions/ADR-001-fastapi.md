# ADR-001: FastAPI Backend Foundation

**Status:** Implemented

## Decision

Use Python 3.12 and FastAPI as the backend and API/orchestration foundation.

## Rationale

FastAPI provides a small typed HTTP boundary for the Switcher while keeping domain and execution services independent of HTTP. Pydantic request validation is used at the API boundary, and business failures remain represented by the canonical transaction state rather than by HTTP-layer control flow.

The current implementation exposes health checking and a narrow Vendor A airtime transaction endpoint. It is not yet a generic transaction API or agent interface.
