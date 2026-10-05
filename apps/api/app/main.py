"""FastAPI application entry point for Agentic Switcher."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.app.config import settings
from apps.api.app.database import get_db
from apps.api.app.domain.transaction import Transaction, TransactionState
from apps.api.app.mcp_server.app import create_mcp_server, mcp_asgi_app
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.persistence_service import PersistedTransactionExecutionService
from switcher.vendor_adapter_resolver import (
    VendorAuthenticationError,
    create_authenticated_adapter,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run MCP session infrastructure for the lifetime of the host API."""
    mcp_server, sdk_app = create_mcp_server()
    mcp_asgi_app.set_application(sdk_app)
    try:
        async with mcp_server.session_manager.run():
            yield
    finally:
        mcp_asgi_app.set_application(None)


app = FastAPI(
    title="Agentic Switcher",
    description="Agentic transaction orchestration and operations platform",
    version="0.1.0",
    lifespan=lifespan,
)


class AirtimeTransactionRequest(BaseModel):
    """Input accepted by the first Vendor A airtime transaction endpoint."""

    product_type: str
    network: str
    beneficiary: str
    amount: Decimal = Field(gt=0)


class TransactionResponse(BaseModel):
    """Transaction details returned after synchronous execution."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_type: str
    network: str | None
    beneficiary: str | None
    amount: Decimal
    state: TransactionState
    vendor_code: str | None
    vendor_reference: str | None
    error_message: str | None


@app.get("/health")
def health() -> dict[str, str]:
    """Return the health status of the API."""
    return {
        "status": "ok",
        "service": "agentic-switcher-api",
    }


@app.post("/transactions", response_model=TransactionResponse)
def create_transaction(
    request: AirtimeTransactionRequest,
    db: Session = Depends(get_db),
) -> Transaction:
    """Execute and persist the explicitly wired Vendor A airtime flow."""
    try:
        adapter = create_authenticated_adapter("vendor_a", settings)
    except VendorAuthenticationError as error:
        raise HTTPException(
            status_code=503,
            detail="Vendor adapter authentication failed",
        ) from error

    transaction = Transaction(
        product_type=request.product_type,
        network=request.network,
        beneficiary=request.beneficiary,
        amount=request.amount,
    )
    execution_service = TransactionExecutionService(adapter)
    persistence_service = PersistedTransactionExecutionService(db, execution_service)
    return persistence_service.execute(transaction)


app.mount("/mcp", mcp_asgi_app)
