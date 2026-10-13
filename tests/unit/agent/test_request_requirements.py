"""Unit tests for the non-authoritative request-requirements reader.

These lock in that a beneficiary spoken with separators ("0803 000 0001") is
recognized by the same parser rules the conversation layer relies on, and that
the phone digits are never reinterpreted as the amount.
"""

from decimal import Decimal

from agent.request_requirements import inspect_request


def test_spaced_beneficiary_completes_a_multi_turn_request() -> None:
    combined = " ".join(["Buy ₦5,000 MTN airtime", "0803 000 0001"])

    requirements = inspect_request(combined)

    assert requirements.missing_fields == ()
    assert requirements.beneficiary == "08030000001"
    assert isinstance(requirements.beneficiary, str)
    assert requirements.amount == Decimal("5000.00")
    assert requirements.network == "MTN"
    assert requirements.complete is not None
    assert requirements.complete.beneficiary == "08030000001"


def test_spaced_phone_digits_are_not_read_as_an_amount() -> None:
    requirements = inspect_request("beneficiary number 0803 000 0001")

    assert requirements.beneficiary == "08030000001"
    assert requirements.amount is None


def test_partial_spaced_beneficiary_is_reported_as_missing() -> None:
    requirements = inspect_request("Buy ₦5,000 MTN airtime for 0803 00")

    assert "beneficiary" in requirements.missing_fields
    assert requirements.beneficiary is None
