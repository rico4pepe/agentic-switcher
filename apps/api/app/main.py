"""FastAPI application entry point for Agentic Switcher."""

from decimal import Decimal
from uuid import UUID

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.app.database import get_db
from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.persistence_service import PersistedTransactionExecutionService
from vendors.base.models import AuthenticationRequest
from vendors.vendor_a import VendorAAdapter


app = FastAPI(
    title="Agentic Switcher",
    description="Agentic transaction orchestration and operations platform",
    version="0.1.0",
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
    adapter = VendorAAdapter()
    adapter.authenticate(AuthenticationRequest({"api_key": "vendor_a_test_key"}))

    transaction = Transaction(
        product_type=request.product_type,
        network=request.network,
        beneficiary=request.beneficiary,
        amount=request.amount,
    )
    execution_service = TransactionExecutionService(adapter)
    persistence_service = PersistedTransactionExecutionService(db, execution_service)
    return persistence_service.execute(transaction)
