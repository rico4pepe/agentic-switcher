"""Regression tests: an equivalent *unresolved* request must never submit a
second vendor operation.

Background: the chat orchestrator mints a fresh idempotency key on every call,
so a retry after a timeout (and failed status query) used to look like a brand
new purchase and was submitted to the vendor again. The persistence layer now
detects an equivalent operation that may still be executing and returns /
reconciles that one instead.

What must NOT change (and is re-asserted here): same-key replay, same-key /
different-input conflict, and the ability to make a legitimate new purchase once
the earlier equivalent transaction is terminal.

All vendors are simulated; no real airtime purchase is possible.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

import apps.api.app.mcp_server.app as mcp_app
from apps.api.app.conversations import reset_conversations
from apps.api.app.database import SessionLocal
from apps.api.app.domain.transaction import Transaction, TransactionState
from apps.api.app.main import app
from switcher.demo.scenarios import DemoScenarioName, set_demo_scenario
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.persistence_service import (
    UNRESOLVED_STATES,
    EquivalenceKey,
    ExecutionMatch,
    IdempotencyConflictError,
    PersistedTransactionExecutionService,
)
from vendor_fakes import (
    ScriptedVendor,
    delete_transactions,
    failed,
    new_transaction_ids,
    success,
    unique_beneficiary,
    unknown,
)

POLICY_BENEFICIARY = "08030000001"
CHAT_MESSAGE = "Buy ₦5,000 MTN airtime for 08030000001."


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


@pytest.fixture
def created_ids(session: Session) -> Iterator[list[UUID]]:
    """Track ids; also sweep any row created for the test's beneficiaries."""
    ids: list[UUID] = []
    yield ids
    delete_transactions(session, ids)


@pytest.fixture
def policy_account_cleanup() -> Iterator[None]:
    with SessionLocal() as db:
        before = set(
            db.scalars(
                select(Transaction.id).where(
                    Transaction.beneficiary == POLICY_BENEFICIARY
                )
            )
        )
    yield
    created = new_transaction_ids(POLICY_BENEFICIARY, before)
    with SessionLocal() as db:
        delete_transactions(db, created)


@pytest.fixture
def client() -> Iterator[TestClient]:
    reset_conversations()
    with TestClient(app) as test_client:
        yield test_client
    reset_conversations()


def make_transaction(
    beneficiary: str,
    *,
    key: str | None = None,
    amount: str | Decimal = "5000.00",
    network: str | None = "MTN",
    product_type: str = "airtime",
    vendor_code: str | None = None,
) -> Transaction:
    return Transaction(
        product_type=product_type,
        network=network,
        beneficiary=beneficiary,
        amount=Decimal(amount),
        idempotency_key=key,
        vendor_code=vendor_code,
    )


def new_key() -> str:
    return f"guard-{uuid4()}"


def service_for(
    session: Session,
    vendor: ScriptedVendor,
    *,
    vendors: dict[str, ScriptedVendor] | None = None,
) -> PersistedTransactionExecutionService:
    factory: Callable[[str], TransactionExecutionService] | None = None
    if vendors is not None:
        factory = lambda code: TransactionExecutionService(vendors[code])  # noqa: E731
    return PersistedTransactionExecutionService(
        session,
        TransactionExecutionService(vendor),
        vendor_execution_service_factory=factory,
    )


def uncertain_vendor(**kwargs) -> ScriptedVendor:
    """Submission times out; status queries stay unresolved unless scripted."""
    return ScriptedVendor(
        submit_script=(TimeoutError("scripted timeout"),),
        query_script=kwargs.pop("query_script", (unknown(),)),
        **kwargs,
    )


def row_count(beneficiary: str) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.beneficiary == beneficiary)
        )


def persisted(transaction_id: UUID) -> Transaction:
    with SessionLocal() as db:
        row = db.get(Transaction, transaction_id)
        assert row is not None
        db.expunge(row)
        return row


def lock_is_free(key: int) -> bool:
    """True if the advisory lock can be taken right now from another session."""
    with SessionLocal() as other:
        acquired = other.scalar(
            text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}
        )
        other.rollback()
    return bool(acquired)


# --------------------------------------------------------------------------
# behaviour that must remain unchanged
# --------------------------------------------------------------------------


def test_same_key_replay_is_unchanged_and_does_not_resubmit(
    session: Session, created_ids: list[UUID]
):
    vendor = uncertain_vendor()
    beneficiary = unique_beneficiary()
    key = new_key()
    service = service_for(session, vendor)

    first = service.execute_with_outcome(make_transaction(beneficiary, key=key))
    created_ids.append(first.transaction.id)
    replay = service.execute_with_outcome(make_transaction(beneficiary, key=key))

    assert first.match == ExecutionMatch.NEW
    assert replay.match == ExecutionMatch.IDEMPOTENT_REPLAY
    assert replay.transaction.id == first.transaction.id
    assert vendor.submissions == [first.transaction.id]
    assert row_count(beneficiary) == 1


def test_same_key_with_different_inputs_still_conflicts_and_releases_lock(
    session: Session, created_ids: list[UUID]
):
    vendor = uncertain_vendor()
    beneficiary = unique_beneficiary()
    key = new_key()
    service = service_for(session, vendor)
    first = service.execute(make_transaction(beneficiary, key=key))
    created_ids.append(first.id)
    submissions_before = list(vendor.submissions)

    conflicting = make_transaction(beneficiary, key=key, amount="6000.00")
    with pytest.raises(IdempotencyConflictError):
        service.execute(conflicting)

    assert vendor.submissions == submissions_before
    assert row_count(beneficiary) == 1
    # Nothing was left holding the advisory lock for the rejected request.
    assert lock_is_free(EquivalenceKey.from_transaction(conflicting).lock_key())


def test_unique_idempotency_key_violation_rolls_back_and_releases_lock(
    session: Session, created_ids: list[UUID]
):
    """Same key, different inputs, racing past the pre-check, hits the DB unique
    constraint; the guard's transaction must roll back and free its lock."""
    vendor = uncertain_vendor()
    beneficiary = unique_beneficiary()
    key = new_key()
    first = service_for(session, vendor).execute(
        make_transaction(beneficiary, key=key)
    )
    created_ids.append(first.id)

    loser = make_transaction(beneficiary, key=key, amount="7000.00")
    other_session = SessionLocal()
    try:
        service = service_for(other_session, vendor)
        # Defeat the pre-check so the insert itself raises IntegrityError.
        service._find_by_idempotency_key = _hide_first_lookup(service)  # type: ignore[method-assign]
        with pytest.raises(IdempotencyConflictError):
            service.execute(loser)
    finally:
        other_session.close()

    assert row_count(beneficiary) == 1
    assert lock_is_free(EquivalenceKey.from_transaction(loser).lock_key())


def _hide_first_lookup(service: PersistedTransactionExecutionService):
    original = service._find_by_idempotency_key
    calls = {"n": 0}

    def lookup(key: str):
        calls["n"] += 1
        return None if calls["n"] == 1 else original(key)

    return lookup


# --------------------------------------------------------------------------
# the guard itself (persistence layer)
# --------------------------------------------------------------------------


def test_equivalent_request_with_new_key_returns_existing_unresolved_operation(
    session: Session, created_ids: list[UUID]
):
    vendor = uncertain_vendor()
    beneficiary = unique_beneficiary()
    service = service_for(session, vendor)
    first = service.execute(make_transaction(beneficiary, key=new_key()))
    created_ids.append(first.id)
    assert first.state == TransactionState.UNKNOWN

    retry = make_transaction(beneficiary, key=new_key())
    outcome = service.execute_with_outcome(retry)

    assert outcome.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert outcome.transaction.id == first.id
    assert outcome.transaction.state == TransactionState.UNKNOWN
    assert outcome.transaction.vendor_code == first.vendor_code
    # The retry was never persisted and never reached the vendor's submit.
    assert vendor.submissions == [first.id]
    assert row_count(beneficiary) == 1
    with SessionLocal() as db:
        assert db.get(Transaction, retry.id) is None
    # The guard's lock was released before returning.
    assert lock_is_free(EquivalenceKey.from_transaction(retry).lock_key())


def test_timeout_then_failed_status_query_then_equivalent_retry_never_resubmits(
    session: Session, created_ids: list[UUID]
):
    vendor = uncertain_vendor(query_script=(ConnectionError("down"),))
    beneficiary = unique_beneficiary()
    service = service_for(session, vendor)

    first = service.execute(make_transaction(beneficiary, key=new_key()))
    created_ids.append(first.id)
    assert first.state == TransactionState.UNKNOWN

    retry = service.execute_with_outcome(make_transaction(beneficiary, key=new_key()))

    assert retry.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert retry.transaction.id == first.id
    assert retry.transaction.state == TransactionState.UNKNOWN
    assert vendor.submissions == [first.id]  # no duplicate submission
    assert vendor.queries == [first.id, first.id]  # original op re-queried
    assert row_count(beneficiary) == 1


def test_equivalent_retry_reconciles_the_original_vendor_operation(
    session: Session, created_ids: list[UUID]
):
    vendor = uncertain_vendor(query_script=(ConnectionError("down"),))
    beneficiary = unique_beneficiary()
    service = service_for(session, vendor)
    first = service.execute(make_transaction(beneficiary, key=new_key()))
    created_ids.append(first.id)

    vendor.set_query_script(success("ref-original"))
    retry = service.execute_with_outcome(make_transaction(beneficiary, key=new_key()))

    assert retry.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert retry.transaction.id == first.id
    assert retry.transaction.state == TransactionState.SUCCESS
    assert retry.transaction.vendor_reference == "ref-original"
    assert vendor.submissions == [first.id]
    assert row_count(beneficiary) == 1


@pytest.mark.parametrize(
    ("submit_result", "terminal_state"),
    [(success("ref-1"), TransactionState.SUCCESS), (failed(), TransactionState.FAILED)],
)
def test_terminal_transaction_does_not_block_a_legitimate_new_purchase(
    session: Session,
    created_ids: list[UUID],
    submit_result,
    terminal_state: TransactionState,
):
    vendor = ScriptedVendor(submit_script=(submit_result,))
    beneficiary = unique_beneficiary()
    service = service_for(session, vendor)

    first = service.execute_with_outcome(make_transaction(beneficiary, key=new_key()))
    created_ids.append(first.transaction.id)
    assert first.transaction.state == terminal_state

    second = service.execute_with_outcome(make_transaction(beneficiary, key=new_key()))
    created_ids.append(second.transaction.id)

    assert second.match == ExecutionMatch.NEW
    assert second.transaction.id != first.transaction.id
    assert vendor.submissions == [first.transaction.id, second.transaction.id]
    assert row_count(beneficiary) == 2


@pytest.mark.parametrize(
    "variation",
    [
        {"beneficiary": "other"},
        {"amount": "5001.00"},
        {"network": "AIRTEL"},
        {"network": None},
        {"product_type": "data"},
    ],
    ids=["beneficiary", "amount", "network", "network-none", "product-type"],
)
def test_materially_different_requests_are_independent_operations(
    session: Session, created_ids: list[UUID], variation: dict[str, object]
):
    vendor = uncertain_vendor()
    beneficiary = unique_beneficiary()
    service = service_for(session, vendor)
    first = service.execute(make_transaction(beneficiary, key=new_key()))
    created_ids.append(first.id)

    fields = dict(variation)
    if fields.get("beneficiary") == "other":
        fields["beneficiary"] = unique_beneficiary()
    kwargs = {"beneficiary": beneficiary, **fields}
    second = service.execute_with_outcome(make_transaction(key=new_key(), **kwargs))
    created_ids.append(second.transaction.id)

    assert second.match == ExecutionMatch.NEW
    assert second.transaction.id != first.id
    assert vendor.submissions == [first.id, second.transaction.id]


def test_account_isolation_two_beneficiaries_never_share_an_operation(
    session: Session, created_ids: list[UUID]
):
    vendor = uncertain_vendor()
    service = service_for(session, vendor)
    a = service.execute(make_transaction(unique_beneficiary(), key=new_key()))
    b = service.execute(make_transaction(unique_beneficiary(), key=new_key()))
    created_ids.extend([a.id, b.id])

    assert a.id != b.id
    assert vendor.submissions == [a.id, b.id]


def test_equivalence_ignores_formatting_but_not_substance(
    session: Session, created_ids: list[UUID]
):
    vendor = uncertain_vendor()
    beneficiary = unique_beneficiary()
    service = service_for(session, vendor)
    first = service.execute(make_transaction(beneficiary, key=new_key(), amount="5000"))
    created_ids.append(first.id)

    same = service.execute_with_outcome(
        make_transaction(
            beneficiary, key=new_key(), amount="5000.00", network=" mtn "
        )
    )

    assert same.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert same.transaction.id == first.id
    assert vendor.submissions == [first.id]


@pytest.mark.parametrize(
    "state",
    [
        TransactionState.SUBMITTING,
        TransactionState.SUBMITTED,
        TransactionState.UNKNOWN,
        TransactionState.INVESTIGATING,
        TransactionState.STATUS_RESOLVED,
    ],
)
def test_every_in_flight_state_matches_without_submitting(
    session: Session, created_ids: list[UUID], state: TransactionState
):
    beneficiary = unique_beneficiary()
    existing = make_transaction(beneficiary, key=new_key(), vendor_code="vendor_a")
    existing.state = state
    session.add(existing)
    session.commit()
    created_ids.append(existing.id)
    vendor = ScriptedVendor(query_script=(unknown(),))

    outcome = service_for(session, vendor).execute_with_outcome(
        make_transaction(beneficiary, key=new_key(), vendor_code="vendor_a")
    )

    assert outcome.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert outcome.transaction.id == existing.id
    assert vendor.submissions == []  # reconcile/return only, never submit
    assert row_count(beneficiary) == 1


@pytest.mark.parametrize(
    "state",
    [
        TransactionState.CREATED,
        TransactionState.VALIDATING,
        TransactionState.VALIDATED,
    ],
)
def test_pre_submission_states_join_the_existing_row_instead_of_duplicating(
    session: Session, created_ids: list[UUID], state: TransactionState
):
    """A concurrent equivalent request must join the committed row, not add one."""
    beneficiary = unique_beneficiary()
    existing = make_transaction(beneficiary, key=new_key())
    existing.state = state
    session.add(existing)
    session.commit()
    created_ids.append(existing.id)
    vendor = ScriptedVendor(submit_script=(success("ref-joined"),))

    outcome = service_for(session, vendor).execute_with_outcome(
        make_transaction(beneficiary, key=new_key())
    )

    assert outcome.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert outcome.transaction.id == existing.id
    assert row_count(beneficiary) == 1
    # The single existing operation is the only thing ever submitted.
    assert vendor.submissions == [existing.id]


@pytest.mark.parametrize(
    "state", [TransactionState.SUCCESS, TransactionState.FAILED]
)
def test_terminal_rows_are_excluded_from_matching(
    session: Session, created_ids: list[UUID], state: TransactionState
):
    beneficiary = unique_beneficiary()
    existing = make_transaction(beneficiary, key=new_key())
    existing.state = state
    session.add(existing)
    session.commit()
    created_ids.append(existing.id)
    vendor = ScriptedVendor(submit_script=(success("ref-new"),))

    outcome = service_for(session, vendor).execute_with_outcome(
        make_transaction(beneficiary, key=new_key())
    )
    created_ids.append(outcome.transaction.id)

    assert outcome.match == ExecutionMatch.NEW
    assert outcome.transaction.id != existing.id


def test_existing_operation_is_reconciled_through_its_own_vendor_not_rerouted(
    session: Session, created_ids: list[UUID]
):
    vendor_a = uncertain_vendor(query_script=(ConnectionError("down"),))
    vendor_b = ScriptedVendor("vendor_b", submit_script=(success("ref-b"),))
    vendors = {"vendor_a": vendor_a, "vendor_b": vendor_b}
    beneficiary = unique_beneficiary()

    first = service_for(session, vendor_a, vendors=vendors).execute(
        make_transaction(beneficiary, key=new_key(), vendor_code="vendor_a")
    )
    created_ids.append(first.id)
    assert first.state == TransactionState.UNKNOWN

    # The retry would now route to vendor B; vendor A later confirms success.
    vendor_a.set_query_script(success("ref-a-final"))
    retry = service_for(session, vendor_b, vendors=vendors).execute_with_outcome(
        make_transaction(beneficiary, key=new_key(), vendor_code="vendor_b")
    )

    assert retry.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert retry.transaction.id == first.id
    assert retry.transaction.vendor_code == "vendor_a"
    assert retry.transaction.state == TransactionState.SUCCESS
    assert retry.transaction.vendor_reference == "ref-a-final"
    assert vendor_a.queries == [first.id]  # reconciled via the owning vendor
    assert vendor_b.submissions == []
    assert vendor_b.queries == []
    assert vendor_b.validations == 0


def test_without_a_vendor_resolver_a_foreign_vendor_operation_is_left_untouched(
    session: Session, created_ids: list[UUID]
):
    vendor_a = uncertain_vendor()
    vendor_b = ScriptedVendor("vendor_b", submit_script=(success("ref-b"),))
    beneficiary = unique_beneficiary()
    first = service_for(session, vendor_a).execute(
        make_transaction(beneficiary, key=new_key(), vendor_code="vendor_a")
    )
    created_ids.append(first.id)
    queries_before = len(vendor_a.queries)

    retry = service_for(session, vendor_b).execute_with_outcome(
        make_transaction(beneficiary, key=new_key(), vendor_code="vendor_b")
    )

    assert retry.match == ExecutionMatch.EQUIVALENT_UNRESOLVED
    assert retry.transaction.id == first.id
    assert retry.transaction.state == TransactionState.UNKNOWN
    assert len(vendor_a.queries) == queries_before  # not queried by the retry
    assert vendor_b.submissions == [] and vendor_b.queries == []


def test_advisory_lock_is_not_held_across_the_vendor_submission(
    session: Session, created_ids: list[UUID]
):
    beneficiary = unique_beneficiary()
    probe = make_transaction(beneficiary, key=new_key())
    key = EquivalenceKey.from_transaction(probe).lock_key()
    observed: list[bool] = []
    vendor = ScriptedVendor(
        submit_script=(success("ref-slow"),),
        on_submit=lambda request: observed.append(lock_is_free(key)),
    )

    outcome = service_for(session, vendor).execute_with_outcome(probe)
    created_ids.append(outcome.transaction.id)

    assert observed == [True]  # lock was free while the vendor call ran


# --------------------------------------------------------------------------
# concurrency
# --------------------------------------------------------------------------


def test_equivalent_request_waits_on_the_advisory_lock_before_doing_any_work(
    created_ids: list[UUID],
):
    """Deterministic: hold the lock from another connection and observe that an
    equivalent request blocks (no insert, no vendor call) until it is released,
    while an unrelated operation is not blocked."""
    beneficiary = unique_beneficiary()
    request = make_transaction(beneficiary, key=new_key())
    key = EquivalenceKey.from_transaction(request).lock_key()
    vendor = uncertain_vendor()

    def run(tx: Transaction):
        with SessionLocal() as db:
            return service_for(db, vendor).execute_with_outcome(tx)

    holder = SessionLocal()
    try:
        holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
        with ThreadPoolExecutor(max_workers=2) as pool:
            blocked = pool.submit(run, request)
            with pytest.raises(FutureTimeout):
                blocked.result(timeout=0.75)  # still waiting on the lock
            assert vendor.validations == 0
            assert vendor.submissions == []
            assert row_count(beneficiary) == 0

            # A different operation hashes to a different lock: not blocked.
            other_tx = make_transaction(unique_beneficiary(), key=new_key())
            other = pool.submit(run, other_tx).result(timeout=10)
            created_ids.append(other.transaction.id)
            assert other.match == ExecutionMatch.NEW

            holder.rollback()  # release the lock
            result = blocked.result(timeout=10)
    finally:
        holder.rollback()
        holder.close()

    created_ids.append(result.transaction.id)
    assert result.match == ExecutionMatch.NEW
    assert row_count(beneficiary) == 1
    assert len([s for s in vendor.submissions if s == result.transaction.id]) == 1


def test_concurrent_equivalent_requests_with_different_keys_create_one_operation(
    created_ids: list[UUID],
):
    workers = 8
    beneficiary = unique_beneficiary()
    vendor = uncertain_vendor()
    start = Barrier(workers)

    def attempt(_: int):
        with SessionLocal() as db:
            tx = make_transaction(beneficiary, key=new_key())
            start.wait(timeout=10)
            return service_for(db, vendor).execute_with_outcome(tx)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = [f.result(timeout=30) for f in [pool.submit(attempt, i) for i in range(workers)]]

    ids = {o.transaction.id for o in outcomes}
    created_ids.extend(ids)

    assert len(ids) == 1, "every concurrent equivalent request saw one operation"
    assert row_count(beneficiary) == 1
    assert sum(o.match == ExecutionMatch.NEW for o in outcomes) == 1
    assert all(
        o.match in {ExecutionMatch.NEW, ExecutionMatch.EQUIVALENT_UNRESOLVED}
        for o in outcomes
    )
    assert vendor.submissions == [next(iter(ids))]  # exactly one vendor submission
    assert persisted(next(iter(ids))).state in UNRESOLVED_STATES


def test_concurrent_requests_with_the_same_key_remain_idempotent_replays(
    created_ids: list[UUID],
):
    workers = 6
    beneficiary = unique_beneficiary()
    key = new_key()
    vendor = uncertain_vendor()
    start = Barrier(workers)

    def attempt(_: int):
        with SessionLocal() as db:
            tx = make_transaction(beneficiary, key=key)
            start.wait(timeout=10)
            return service_for(db, vendor).execute_with_outcome(tx)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = [f.result(timeout=30) for f in [pool.submit(attempt, i) for i in range(workers)]]

    ids = {o.transaction.id for o in outcomes}
    created_ids.extend(ids)

    assert len(ids) == 1
    assert row_count(beneficiary) == 1
    assert sum(o.match == ExecutionMatch.NEW for o in outcomes) == 1
    # Losers are replays of their own key, never reported as duplicates.
    assert not any(
        o.match == ExecutionMatch.EQUIVALENT_UNRESOLVED for o in outcomes
    )
    assert vendor.submissions == [next(iter(ids))]


# --------------------------------------------------------------------------
# MCP business path (policy + routing + guard together)
# --------------------------------------------------------------------------


def install_vendors(
    monkeypatch: pytest.MonkeyPatch, vendors: dict[str, ScriptedVendor]
) -> None:
    monkeypatch.setattr(
        mcp_app,
        "create_authenticated_adapter",
        lambda vendor_code, settings: vendors[vendor_code],
    )


def mcp_execute(key: str, *, amount: str = "5000.00"):
    return mcp_app._execute_transaction(
        mcp_app.ExecuteTransactionRequest(
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary=POLICY_BENEFICIARY,
            amount=amount,
            idempotency_key=key,
        )
    )


def test_mcp_equivalent_retry_returns_the_existing_transaction_truthfully(
    monkeypatch: pytest.MonkeyPatch, policy_account_cleanup: None
):
    vendor = uncertain_vendor(query_script=(ConnectionError("down"),))
    install_vendors(monkeypatch, {"vendor_a": vendor, "vendor_b": vendor})

    first = mcp_execute(new_key())
    retry = mcp_execute(new_key())  # new key, like every chat request

    assert first.status == "unknown" and first.transaction_id is not None
    assert retry.transaction_id == first.transaction_id
    assert retry.status == "unknown"
    assert retry.action == "allow"
    assert "already awaiting confirmation" in retry.message
    assert "No additional purchase was submitted" in retry.message
    assert vendor.submissions == [first.transaction_id]


def test_mcp_retry_reports_the_reconciled_outcome_of_the_original(
    monkeypatch: pytest.MonkeyPatch, policy_account_cleanup: None
):
    vendor = uncertain_vendor(query_script=(ConnectionError("down"),))
    install_vendors(monkeypatch, {"vendor_a": vendor, "vendor_b": vendor})
    first = mcp_execute(new_key())

    vendor.set_query_script(success("ref-mcp-final"))
    retry = mcp_execute(new_key())

    assert retry.transaction_id == first.transaction_id
    assert retry.status == "success"
    assert retry.vendor_reference == "ref-mcp-final"
    assert "No additional purchase was submitted" in retry.message
    assert vendor.submissions == [first.transaction_id]

    # Now terminal, so a genuinely new purchase is allowed again.
    vendor_next = ScriptedVendor(submit_script=(success("ref-new"),))
    install_vendors(monkeypatch, {"vendor_a": vendor_next, "vendor_b": vendor_next})
    later = mcp_execute(new_key())
    assert later.transaction_id != first.transaction_id
    assert later.status == "success"
    assert vendor_next.submissions == [later.transaction_id]


def test_mcp_retry_is_not_rerouted_when_the_original_vendor_becomes_unavailable(
    monkeypatch: pytest.MonkeyPatch, policy_account_cleanup: None
):
    vendor_a = uncertain_vendor(query_script=(ConnectionError("down"),))
    vendor_b = ScriptedVendor("vendor_b", submit_script=(success("ref-b"),))
    install_vendors(monkeypatch, {"vendor_a": vendor_a, "vendor_b": vendor_b})
    first = mcp_execute(new_key())
    assert first.vendor_code == "vendor_a"

    set_demo_scenario(DemoScenarioName.VENDOR_A_UNAVAILABLE)  # would pick B
    retry = mcp_execute(new_key())

    assert retry.transaction_id == first.transaction_id
    assert retry.vendor_code == "vendor_a"
    assert vendor_b.submissions == []
    assert vendor_b.validations == 0
    assert vendor_a.submissions == [first.transaction_id]


# --------------------------------------------------------------------------
# REST (/api/chat): the originally observed failure
# --------------------------------------------------------------------------


def test_chat_retry_after_timeout_and_failed_status_query_does_not_duplicate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    policy_account_cleanup: None,
):
    vendor = uncertain_vendor(query_script=(ConnectionError("down"),))
    install_vendors(monkeypatch, {"vendor_a": vendor, "vendor_b": vendor})

    first = client.post("/api/chat", json={"message": CHAT_MESSAGE})
    second = client.post("/api/chat", json={"message": CHAT_MESSAGE})

    assert first.status_code == second.status_code == 200
    one, two = first.json(), second.json()
    assert one["status"] == two["status"] == "unknown"
    assert one["transaction_id"] is not None
    assert two["transaction_id"] == one["transaction_id"]
    assert "could not be confirmed" in two["explanation"]
    assert "retry" not in two["explanation"].lower()
    assert vendor.submissions == [UUID(one["transaction_id"])]
    assert row_count(POLICY_BENEFICIARY) >= 1
    with SessionLocal() as db:
        persisted_ids = db.scalars(
            select(Transaction.id).where(
                Transaction.id == UUID(one["transaction_id"])
            )
        ).all()
    assert len(persisted_ids) == 1


def test_chat_retry_reflects_original_outcome_once_the_vendor_confirms(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    policy_account_cleanup: None,
):
    vendor = uncertain_vendor(query_script=(ConnectionError("down"),))
    install_vendors(monkeypatch, {"vendor_a": vendor, "vendor_b": vendor})
    first = client.post("/api/chat", json={"message": CHAT_MESSAGE}).json()

    vendor.set_query_script(success("ref-chat-final"))
    second = client.post("/api/chat", json={"message": CHAT_MESSAGE})

    assert second.status_code == 200
    body = second.json()
    assert body["transaction_id"] == first["transaction_id"]
    assert body["status"] == "success"
    assert body["vendor_reference"] == "ref-chat-final"
    assert vendor.submissions == [UUID(first["transaction_id"])]
