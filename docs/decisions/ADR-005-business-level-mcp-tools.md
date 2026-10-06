# ADR-005: Business-Level MCP Tools

**Status:** Partially implemented

## Decision

The MCP boundary exposes business-level tools rather than general-purpose transport tools.
The current MCP server exposes:

- `find_transaction_capabilities()`
- `execute_transaction()`

Planned business tools include:

- `get_account_context()`
- `validate_customer()`
- `get_transaction_status()`
- `investigate_transaction()`

MCP is a business-level interface; the deterministic transaction engine remains
authoritative for persistence, idempotency, execution, and transaction state.

Generic tools such as `call_api()`, `execute_http()`, and `request_url()` are intentionally outside this architecture. They would let an agent bypass capability, policy, transaction, and adapter controls.
