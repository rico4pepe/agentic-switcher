"""Protocol-level integration tests for MCP capability discovery."""

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from apps.api.app.database import SessionLocal, engine
from apps.api.app.main import app
from apps.api.app.persistence.capability import CapabilityRecord, capability_to_record
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


@pytest.fixture
def postgres_session() -> Iterator[Session]:
    assert engine.dialect.name == "postgresql"
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def capability_ids(
    postgres_session: Session,
) -> Iterator[list[UUID]]:
    ids: list[UUID] = []
    try:
        yield ids
    finally:
        postgres_session.rollback()
        if ids:
            postgres_session.execute(
                delete(CapabilityRecord).where(CapabilityRecord.id.in_(ids))
            )
            postgres_session.commit()


def create_capability(
    *,
    vendor_code: str,
    service_type: str,
    product_type: str,
    network: str | None,
) -> Capability:
    return Capability(
        vendor_code=vendor_code,
        service_type=service_type,
        product_type=product_type,
        network=network,
        supported_operations=frozenset(CapabilityOperation),
        workflow=(
            WorkflowStep(CapabilityOperation.AUTHENTICATE, required=True),
            WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION, required=False),
        ),
        product_attributes={"origin": "mcp-integration-test"},
    )


def persist_capability(
    session: Session,
    capability_ids: list[UUID],
    capability: Capability,
) -> None:
    record = capability_to_record(capability)
    session.add(record)
    session.commit()
    capability_ids.append(record.id)


def call_find_capabilities(
    *,
    service_type: str,
    product_type: str,
    network: str | None,
) -> dict[str, object]:
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "find_transaction_capabilities",
                    "arguments": {
                        "service_type": service_type,
                        "product_type": product_type,
                        "network": network,
                    },
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "find_transaction_capabilities",
                "Mcp-Protocol-Version": "2026-07-28",
            },
        )

    assert response.status_code == 200, response.text
    return response.json()["result"]["structuredContent"]


def test_mcp_lookup_returns_seeded_canonical_capability_and_json_safe_fields():
    result = call_find_capabilities(
        service_type="airtime",
        product_type="airtime",
        network="MTN",
    )

    assert json.loads(json.dumps(result)) == result
    capability = next(
        item for item in result["capabilities"] if item["vendor_code"] == "vendor_a"
    )
    assert capability == {
        "vendor_code": "vendor_a",
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "supported_operations": [
            "authenticate",
            "execute_transaction",
            "query_transaction",
            "validate_customer",
        ],
        "workflow": [
            {"operation": "authenticate", "required": True},
            {"operation": "validate_customer", "required": True},
            {"operation": "execute_transaction", "required": True},
            {"operation": "query_transaction", "required": True},
        ],
        "product_attributes": {},
    }


def test_mcp_lookup_returns_multiple_matches_without_vendor_ranking(
    postgres_session: Session,
    capability_ids: list[UUID],
):
    identity = uuid4().hex
    service_type = f"mcp-service-{identity}"
    vendor_codes = [f"vendor-{identity}-b", f"vendor-{identity}-a"]
    for vendor_code in vendor_codes:
        persist_capability(
            postgres_session,
            capability_ids,
            create_capability(
                vendor_code=vendor_code,
                service_type=service_type,
                product_type="product",
                network="network",
            ),
        )

    result = call_find_capabilities(
        service_type=service_type,
        product_type="product",
        network="network",
    )

    assert [item["vendor_code"] for item in result["capabilities"]] == sorted(
        vendor_codes
    )


def test_mcp_lookup_network_none_matches_only_canonical_null_network(
    postgres_session: Session,
    capability_ids: list[UUID],
):
    identity = uuid4().hex
    service_type = f"mcp-null-service-{identity}"
    for suffix, network in (("null", None), ("named", "MTN")):
        persist_capability(
            postgres_session,
            capability_ids,
            create_capability(
                vendor_code=f"vendor-{identity}-{suffix}",
                service_type=service_type,
                product_type="product",
                network=network,
            ),
        )

    result = call_find_capabilities(
        service_type=service_type,
        product_type="product",
        network=None,
    )

    assert [item["vendor_code"] for item in result["capabilities"]] == [
        f"vendor-{identity}-null"
    ]
    assert result["capabilities"][0]["network"] is None


def test_mcp_lookup_returns_empty_capabilities_for_no_match():
    result = call_find_capabilities(
        service_type=f"missing-{uuid4().hex}",
        product_type="missing-product",
        network=None,
    )

    assert result == {"capabilities": []}
