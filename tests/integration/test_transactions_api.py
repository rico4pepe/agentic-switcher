"""PostgreSQL-backed HTTP integration tests for the first transaction endpoint."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal, engine
from apps.api.app.domain.transaction import Transaction, TransactionState
from apps.api.app.main import app
from switcher.vendor_adapter_resolver import VendorAuthenticationError


@pytest.fixture
def postgres_session() -> Iterator[Session]:
    """Provide a cleanup session connected to the configured PostgreSQL database."""
    assert engine.dialect.name == "postgresql"
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def created_transaction_ids(postgres_session: Session) -> Iterator[list[UUID]]:
    """Delete only transactions created through this test module's HTTP calls."""
    transaction_ids: list[UUID] = []
    try:
        yield transaction_ids
    finally:
        postgres_session.rollback()
        if transaction_ids:
            postgres_session.execute(
                delete(Transaction).where(Transaction.id.in_(transaction_ids))
            )
            postgres_session.commit()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Exercise the application without overriding its database dependency."""
    with TestClient(app) as test_client:
        yield test_client


def transaction_payload(*, beneficiary: str = "08030000000") -> dict[str, str]:
    """Build a valid Vendor A airtime request payload."""
    return {
        "product_type": "airtime",
        "network": "MTN",
        "beneficiary": beneficiary,
        "amount": "5000.00",
    }


def post_transaction(
    client: TestClient,
    transaction_ids: list[UUID],
    payload: dict[str, str],
) -> dict[str, object]:
    """Submit a transaction and track its database identifier for cleanup."""
    response = client.post("/transactions", json=payload)
    assert response.status_code == 200
    body = response.json()
    transaction_ids.append(UUID(str(body["id"])))
    return body


def test_successful_airtime_transaction_through_http(
    client: TestClient,
    created_transaction_ids: list[UUID],
):
    body = post_transaction(client, created_transaction_ids, transaction_payload())

    assert body["state"] == TransactionState.SUCCESS.value
    assert body["vendor_code"] == "vendor_a"
    assert body["vendor_reference"] == f"vendor_a-{body['id']}"
    assert body["error_message"] is None


def test_validation_failure_through_http_is_a_failed_transaction(
    client: TestClient,
    created_transaction_ids: list[UUID],
):
    body = post_transaction(
        client,
        created_transaction_ids,
        transaction_payload(beneficiary="08039999999"),
    )

    assert body["state"] == TransactionState.FAILED.value
    assert body["error_message"] == "Customer is not valid for Vendor A MTN airtime"


def test_vendor_authentication_failure_returns_service_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_authentication(vendor_code: str, settings: Settings) -> None:
        raise VendorAuthenticationError(
            f"Authentication failed for vendor: {vendor_code}"
        )

    monkeypatch.setattr(
        "apps.api.app.main.create_authenticated_adapter",
        fail_authentication,
    )

    response = client.post("/transactions", json=transaction_payload())

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Vendor adapter authentication failed",
    }


def test_http_response_contains_persisted_transaction_data(
    client: TestClient,
    created_transaction_ids: list[UUID],
):
    body = post_transaction(client, created_transaction_ids, transaction_payload())

    assert body["product_type"] == "airtime"
    assert body["network"] == "MTN"
    assert body["beneficiary"] == "08030000000"
    assert body["amount"] == "5000.00"


def test_transaction_can_be_reloaded_after_http_request(
    client: TestClient,
    postgres_session: Session,
    created_transaction_ids: list[UUID],
):
    body = post_transaction(client, created_transaction_ids, transaction_payload())
    transaction_id = UUID(str(body["id"]))

    reloaded = postgres_session.get(Transaction, transaction_id)

    assert reloaded is not None
    assert reloaded.id == transaction_id
    assert reloaded.state == TransactionState.SUCCESS
    assert reloaded.vendor_reference == body["vendor_reference"]
