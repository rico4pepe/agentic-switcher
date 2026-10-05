# Amazon Friction Log

Use one entry per genuine development friction. Do not populate this log with hypothetical issues.

## 4I-A — MCP Python SDK 2.3.0

### Streamable HTTP session manager lifecycle

- **Tool / SDK:** Official MCP Python SDK, Streamable HTTP `StreamableHTTPSessionManager`
- **Version:** 2.3.0
- **Task:** Mount the MCP Streamable HTTP ASGI application into the existing FastAPI application and run its tests.
- **Expected:** The same MCP server/session manager could be used over repeated FastAPI `TestClient` lifecycles.
- **Actual:** After one `session_manager.run()` context completed, entering it again raised `RuntimeError`: the manager can only be run once.
- **Impact:** Repeated TestClient lifecycles in the existing API integration tests could not share one MCP server instance.
- **Workaround:** Create a fresh MCP server and Streamable HTTP app for each host-app lifespan and forward requests through a stable mounted ASGI dispatcher.
- **Recommendation:** Make the manager's single-use lifecycle constraint prominent in ASGI mounting documentation, especially for applications and tests that restart their host lifespan.

### MCP transport test Host and request metadata

- **Tool / SDK:** Official MCP Python SDK, Streamable HTTP transport
- **Version:** 2.3.0
- **Task:** Exercise the mounted MCP endpoint using FastAPI `TestClient`.
- **Expected:** A basic request to the mounted endpoint would be accepted by the MCP handler.
- **Actual:** Transport security rejected TestClient's default `testserver` Host with HTTP 421. After using an allowed loopback host, requests still required the v2 `Mcp-Method` header to match the JSON-RPC body method and the protocol/client-capabilities metadata envelope. During `tools/call`, omitting the matching `Mcp-Name` header also returned HTTP 400.
- **Impact:** The initial endpoint checks failed before reaching a successful MCP response until the host and v2 request shape were made explicit.
- **Workaround:** Keep DNS-rebinding protection enabled, allow explicit loopback hosts for local testing, and send the matching `Mcp-Method` (and `Mcp-Name` for `tools/call`), protocol version, and client capabilities metadata. The `tools/list` and `tools/call` requests then returned successfully.
- **Recommendation:** Document the Host allowlist behavior and complete v2 HTTP request examples, including method/name headers and metadata, alongside ASGI mounting guidance.
