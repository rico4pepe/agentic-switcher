"""Integration test for mounting MCP alongside the existing FastAPI app."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app

# The complete set of business-level tools the MCP boundary may expose. Tool
# order in ``tools/list`` is not part of the contract, so it is not asserted.
EXPECTED_TOOL_NAMES = frozenset(
    {
        "find_transaction_capabilities",
        "execute_transaction",
        "get_transaction_status",
    }
)

# Substrings that must never appear in the *name* of a tool input. They would
# indicate vendor routing overrides, credentials, or raw vendor API access.
FORBIDDEN_INPUT_NAME_TOKENS = (
    "vendor",
    "adapter",
    "credential",
    "secret",
    "api_key",
    "apikey",
    "password",
    "token",
    "endpoint",
    "url",
    "raw_",
    "callback",
    "header",
)


def list_mcp_tools() -> dict[str, dict[str, Any]]:
    """Return the tools advertised over MCP, keyed by name (no tool is called)."""
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
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

    assert response.status_code == 200, response.text
    tools = response.json()["result"]["tools"]
    names = [tool["name"] for tool in tools]
    assert len(names) == len(set(names)), f"Duplicate tool names: {names}"
    return {tool["name"]: tool for tool in tools}


def input_property_names(schema: Any) -> set[str]:
    """Collect every property name declared anywhere in a JSON schema."""
    names: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                names.update(value)
            names.update(input_property_names(value))
    elif isinstance(schema, list):
        for item in schema:
            names.update(input_property_names(item))
    return names


def has_free_form_object(schema: Any) -> bool:
    """Return True if a schema allows an arbitrary key/value payload."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or schema.get("additionalProperties"):
            return True
        if "patternProperties" in schema:
            return True
        return any(has_free_form_object(value) for value in schema.values())
    if isinstance(schema, list):
        return any(has_free_form_object(item) for item in schema)
    return False


def json_types(schema: dict[str, Any]) -> set[str]:
    """Return the JSON types a property schema accepts, including anyOf members."""
    types: set[str] = set()
    if "type" in schema:
        types.add(schema["type"])
    for member in schema.get("anyOf", []):
        types.update(json_types(member))
    return types


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
    tool_names = [tool["name"] for tool in result["tools"]]
    assert len(tool_names) == len(set(tool_names))
    assert set(tool_names) == EXPECTED_TOOL_NAMES
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == (
        "Agentic Switcher"
    )


@pytest.mark.parametrize(
    ("tool_name", "expected_properties"),
    [
        (
            "find_transaction_capabilities",
            {"service_type", "product_type", "network"},
        ),
        ("get_transaction_status", {"transaction_id"}),
    ],
)
def test_lookup_tool_input_schemas_expose_only_business_inputs(
    tool_name: str,
    expected_properties: set[str],
):
    schema = list_mcp_tools()[tool_name]["inputSchema"]

    assert schema["type"] == "object"
    assert set(schema["properties"]) == expected_properties
    # Every declared input is mandatory; ``network`` is required but nullable.
    assert set(schema["required"]) == expected_properties
    assert not schema.get("additionalProperties")


def test_find_capabilities_inputs_are_plain_strings():
    properties = list_mcp_tools()["find_transaction_capabilities"]["inputSchema"][
        "properties"
    ]

    assert json_types(properties["service_type"]) == {"string"}
    assert json_types(properties["product_type"]) == {"string"}
    assert json_types(properties["network"]) == {"string", "null"}


def test_status_tool_takes_only_a_uuid_transaction_id():
    properties = list_mcp_tools()["get_transaction_status"]["inputSchema"]["properties"]

    assert properties["transaction_id"]["type"] == "string"
    assert properties["transaction_id"]["format"] == "uuid"


def test_no_tool_input_exposes_vendor_internals_or_free_form_payloads():
    tools = list_mcp_tools()

    assert set(tools) == EXPECTED_TOOL_NAMES
    for tool_name, tool in tools.items():
        schema = tool["inputSchema"]
        offending = sorted(
            name
            for name in input_property_names(schema)
            if any(token in name.lower() for token in FORBIDDEN_INPUT_NAME_TOKENS)
        )
        assert not offending, f"{tool_name} exposes internal inputs: {offending}"
        assert not has_free_form_object(
            schema["properties"]
        ), f"{tool_name} accepts a free-form object payload"
