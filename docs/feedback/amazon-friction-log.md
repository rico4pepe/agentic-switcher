# Amazon Friction Log

Use one entry per genuine development friction. Do not populate this log with hypothetical issues. Entries are grouped by tool; the first group is Amazon tooling, and platform/browser friction is recorded in the same format below it.

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

## Voice input — Browser Web Speech API (non-Amazon platform friction)

- **Tool / API:** Browser Web Speech API `SpeechRecognition` (Chromium `webkitSpeechRecognition`), wrapped by `frontend/src/voice/`.
- **Task:** Add spoken input for financial instructions, including amounts and recipient phone numbers, so a user could dictate an airtime purchase into the existing request field.
- **Expected:** Reliable transcription of the amount and beneficiary, which the user would then review and submit through the normal conversation path.
- **Actual:** Testing with Nigerian English accents and realistic financial instructions exposed misrecognition risk in exactly the fields that matter for a transaction: the amount and the recipient identifier.
- **Impact:** A misheard amount or beneficiary could produce an incorrect transaction. That failure mode is unacceptable for a financial instruction, and the agent must not guess when it cannot reliably identify one.
- **Outcome / decision:** Voice input is disabled by configuration (`VOICE_INPUT_ENABLED = false` in `frontend/src/config.ts`), so the demo accepts typed requests. Voice output (browser Speech Synthesis) remains functional, with text-only and text-plus-voice presentation. The design and runtime are unchanged by voice: it was only ever a client-side input adapter.
- **Recommendation:** Do not treat speech transcription as accurate enough for transaction execution in the amount/recipient fields. Re-enabling voice input is a configuration change, but should gate execution behind explicit confirmation of the parsed amount and beneficiary. This is an observed-risk decision, not a claim that any accent is inherently unreliable.
