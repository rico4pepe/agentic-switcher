"""Deterministic, fully simulated vendor adapter for regression tests.

No real vendor is ever contacted. Behaviour is scripted per test, and every
submission and status query is recorded so tests can assert that a purchase was
never submitted twice.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from threading import Lock
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.database import SessionLocal
from apps.api.app.domain.transaction import Transaction
from vendors.base.adapter import VendorAdapter
from vendors.base.models import (
    AuthenticationRequest,
    AuthenticationResult,
    CustomerValidationRequest,
    CustomerValidationResult,
    TransactionExecutionRequest,
    TransactionQueryRequest,
    VendorCapabilities,
    VendorOperation,
    VendorTransactionResult,
    VendorTransactionStatus,
)
from vendors.vendor_a.operation_ledger import VendorAOperationRecord
from vendors.vendor_b.operation_ledger import VendorBOperationRecord

# A scripted step is either a result to return or an exception to raise.
Step = VendorTransactionResult | BaseException


def success(reference: str = "scripted-ref") -> VendorTransactionResult:
    return VendorTransactionResult(
        status=VendorTransactionStatus.SUCCESS,
        vendor_reference=reference,
        raw_response={"status": "success"},
    )


def failed(message: str = "Scripted vendor failure") -> VendorTransactionResult:
    return VendorTransactionResult(
        status=VendorTransactionStatus.FAILED,
        message=message,
        raw_response={"status": "failed"},
    )


def unknown(message: str | None = None) -> VendorTransactionResult:
    return VendorTransactionResult(
        status=VendorTransactionStatus.UNKNOWN,
        message=message,
    )


class ScriptedVendor(VendorAdapter):
    """A vendor whose submit/query outcomes are scripted and recorded.

    ``submit_script`` and ``query_script`` are consumed in order; the final
    step repeats once the script is exhausted. ``on_submit`` runs inside every
    submission (after it is recorded) so tests can observe concurrent state.
    """

    def __init__(
        self,
        vendor_code: str = "vendor_a",
        *,
        submit_script: Sequence[Step] = (TimeoutError("scripted timeout"),),
        query_script: Sequence[Step] = (unknown(),),
        on_submit: Callable[[TransactionExecutionRequest], None] | None = None,
    ) -> None:
        self.vendor_code = vendor_code
        self._submit_script = list(submit_script)
        self._query_script = list(query_script)
        self._on_submit = on_submit
        self._lock = Lock()
        self.submissions: list[UUID] = []
        self.queries: list[UUID] = []
        self.validations = 0

    def authenticate(self, request: AuthenticationRequest) -> AuthenticationResult:
        return AuthenticationResult(authenticated=True)

    def get_capabilities(self) -> VendorCapabilities:
        return VendorCapabilities(
            vendor_code=self.vendor_code,
            supported_operations=frozenset(VendorOperation),
        )

    def validate_customer(
        self, request: CustomerValidationRequest
    ) -> CustomerValidationResult:
        with self._lock:
            self.validations += 1
        return CustomerValidationResult(is_valid=True)

    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        with self._lock:
            self.submissions.append(request.transaction_id)
            step = self._next(self._submit_script, len(self.submissions) - 1)
        if self._on_submit is not None:
            self._on_submit(request)
        return self._play(step)

    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        with self._lock:
            self.queries.append(request.transaction_id)
            step = self._next(self._query_script, len(self.queries) - 1)
        return self._play(step)

    def set_query_script(self, *steps: Step) -> None:
        """Replace the status-query script (e.g. the vendor recovers)."""
        with self._lock:
            self._query_script = list(steps)
            self.queries.clear()

    @staticmethod
    def _next(script: list[Step], index: int) -> Step:
        return script[min(index, len(script) - 1)]

    @staticmethod
    def _play(step: Step) -> VendorTransactionResult:
        if isinstance(step, BaseException):
            raise step
        return step


def unique_beneficiary() -> str:
    """A beneficiary no other test uses, so equivalence never crosses tests."""
    from uuid import uuid4

    return f"0{int(uuid4().int % 10**10):010d}"


def delete_transactions(session: Session, transaction_ids: Sequence[UUID]) -> None:
    """Remove exactly the given transactions and any simulator ledger rows."""
    if not transaction_ids:
        return
    session.rollback()
    session.execute(
        delete(VendorAOperationRecord).where(
            VendorAOperationRecord.transaction_id.in_(transaction_ids)
        )
    )
    session.execute(
        delete(VendorBOperationRecord).where(
            VendorBOperationRecord.transaction_id.in_(transaction_ids)
        )
    )
    session.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
    session.commit()


def new_transaction_ids(beneficiary: str, before: set[UUID]) -> list[UUID]:
    """Ids of transactions for ``beneficiary`` created since ``before``."""
    with SessionLocal() as session:
        ids = set(
            session.scalars(
                select(Transaction.id).where(Transaction.beneficiary == beneficiary)
            )
        )
    return sorted(ids - before)


def transactions_for(beneficiary: str) -> Iterator[Transaction]:
    with SessionLocal() as session:
        yield from session.scalars(
            select(Transaction)
            .where(Transaction.beneficiary == beneficiary)
            .order_by(Transaction.created_at)
        )
