"""Integration test for mounting MCP alongside the existing FastAPI app."""

from fastapi.testclient import TestClient

from apps.api.app.main import app


def test_mcp_streamable_http_is_mounted_and_fastapi_health_remains_available():
    with TestClient(app, base_url="http://localhost") as client:
        health_response = client.get("/health")
        mcp_response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Method": "tools/list",
                "Mcp-Protocol-Version": "2026-07-28",
            },
        )

    assert health_response.status_code == 200
    assert health_response.json() == {
        "status": "ok",
        "service": "agentic-switcher-api",
    }
    assert mcp_response.status_code == 200
    result = mcp_response.json()["result"]
    assert [tool["name"] for tool in result["tools"]] == [
        "find_transaction_capabilities",
        "execute_transaction",
        "get_transaction_status",
    ]
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == (
        "Agentic Switcher"
    )
