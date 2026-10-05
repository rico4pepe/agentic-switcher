# ADR-005: Business-Level MCP Tools

**Status:** Planned architecture decision; not implemented

## Decision

The future MCP boundary exposes business-level tools rather than general-purpose transport tools:

- `get_account_context()`
- `find_transaction_capabilities()`
- `validate_customer()`
- `execute_transaction()`
- `get_transaction_status()`
- `investigate_transaction()`

Generic tools such as `call_api()`, `execute_http()`, and `request_url()` are intentionally outside this architecture. They would let an agent bypass capability, policy, transaction, and adapter controls.

No MCP server or MCP tools are implemented yet.
