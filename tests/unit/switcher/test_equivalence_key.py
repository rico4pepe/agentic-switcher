"""Unit tests for equivalent-operation identity and the unresolved-state set."""

from decimal import Decimal

import pytest

from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.persistence_service import (
    UNRESOLVED_STATES,
    EquivalenceKey,
)


def tx(**kw) -> Transaction:
    base = dict(product_type="airtime", network="MTN", beneficiary="0803", amount=Decimal("5000"))
    return Transaction(**{**base, **kw})


def key(**kw) -> EquivalenceKey:
    return EquivalenceKey.from_transaction(tx(**kw))


def test_unresolved_and_terminal_states_partition_every_state():
    terminal = {TransactionState.SUCCESS, TransactionState.FAILED}
    assert UNRESOLVED_STATES.isdisjoint(terminal)
    assert UNRESOLVED_STATES | terminal == set(TransactionState)


def test_normalization_ignores_whitespace_case_and_amount_scale():
    a = key()
    b = key(network=" mtn ", amount=Decimal("5000.00"), product_type="AIRTIME")
    assert a == b and a.lock_key() == b.lock_key()


def test_amount_is_rounded_like_the_numeric_column():
    assert key(amount=Decimal("4999.995")).amount == Decimal("5000.00")


@pytest.mark.parametrize(
    "change",
    [{"beneficiary": "0804"}, {"amount": Decimal("5001")}, {"network": "AIRTEL"},
     {"network": None}, {"network": ""}, {"product_type": "data"}],
)
def test_material_differences_change_identity_and_lock(change):
    assert key() != key(**change)
    assert key().lock_key() != key(**change).lock_key()


def test_identity_excludes_key_id_vendor_and_timestamps():
    a = key(idempotency_key="one", vendor_code="vendor_a")
    b = key(idempotency_key="two", vendor_code="vendor_b")
    assert a == b


def test_lock_key_is_stable_and_fits_signed_bigint():
    k = key().lock_key()
    assert k == key().lock_key()
    assert -(2**63) <= k < 2**63
