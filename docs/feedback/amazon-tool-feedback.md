# Amazon Tool Feedback

Use one entry per genuine experience. Do not record assumed or reconstructed feedback.

## 4I-A — MCP Python SDK 2.3.0

- **Date:** 2026-10-05
- **Amazon tool/API/SDK:** Official MCP Python SDK, version 2.3.0
- **What we used it for:** Adding a minimal MCP server and mounting its Streamable HTTP ASGI application into the existing FastAPI application.
- **What worked:** The SDK's current `MCPServer` API and `streamable_http_app()` successfully provided the mounted MCP endpoint. The official documentation helped identify the supported ASGI mounting approach and the need for the host application's lifespan to run the session manager. After addressing the manager lifecycle and local transport-test requirements, the MCP endpoint and full test suite worked successfully.
- **What did not work / needs improvement:** The session manager is single-use, which initially conflicted with repeated FastAPI TestClient lifecycles. Transport security also rejected TestClient's default `testserver` Host with HTTP 421; successful v2 test requests needed explicit local Host handling, `Mcp-Method`, and protocol/client-capabilities metadata.
- **Onboarding experience:** The official ASGI mounting documentation was useful. Runtime behavior around the single-use manager and the v2 HTTP test request requirements took additional investigation, but was resolved without replacing the SDK or changing the application architecture.
- **Would we use it again?:** Yes. The SDK ultimately mounted successfully within FastAPI and passed the complete test suite. The lifecycle and local transport-test constraints are worth accounting for in future work, but did not outweigh the supported ASGI integration.
- **Additional notes:** No business tools, AWS calls, or separate HTTP server were needed for this milestone.
