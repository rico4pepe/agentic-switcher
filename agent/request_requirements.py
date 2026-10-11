"""Structured view of which request fields are present in a message.

This module is a thin, non-authoritative reader layered on top of the
deterministic parser in :mod:`agent.request_understanding`. It reuses the
parser's own field rules rather than re-implementing or narrowing them, so the
interactive conversation layer can ask for missing information without ever
becoming a second validation path.

It performs no execution, routing, policy, vendor, or persistence work.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agent.request_understanding import (
    RequestUnderstanding,
    UnsupportedRequestError,
    _PURCHASE_VERB_RE,
    _parse_amount,
    _parse_beneficiary,
    _parse_network,
    _parse_product,
)
from agent.runtime.service import AgentRequest

# Canonical field names the conversation layer may ask the user to supply.
MISSING_ORDER = ("intent", "product", "amount", "network", "beneficiary")


@dataclass(frozen=True)
class RequestRequirements:
    """Which airtime fields a free-text request currently provides."""

    intent_present: bool
    product: str | None
    amount: Decimal | None
    network: str | None
    beneficiary: str | None
    missing_fields: tuple[str, ...]
    complete: AgentRequest | None

    @property
    def is_complete(self) -> bool:
        return self.complete is not None


def inspect_request(text: str) -> RequestRequirements:
    """Report the fields present in ``text`` using the parser's own rules.

    The authoritative :class:`RequestUnderstanding.parse` is only invoked once
    every field is present, so a structurally complete request is validated by
    exactly the same code path as the legacy boundary.
    """
    normalized = text.strip()
    if not normalized:
        return RequestRequirements(
            intent_present=False,
            product=None,
            amount=None,
            network=None,
            beneficiary=None,
            missing_fields=MISSING_ORDER,
            complete=None,
        )

    intent_present = _PURCHASE_VERB_RE.search(normalized) is not None

    beneficiary: str | None = None
    beneficiary_span = (0, 0)
    try:
        beneficiary, beneficiary_span = _parse_beneficiary(normalized)
    except UnsupportedRequestError:
        pass

    amount: Decimal | None = None
    try:
        amount = _parse_amount(normalized, beneficiary_span)
    except UnsupportedRequestError:
        pass

    network: str | None = None
    try:
        network = _parse_network(normalized)
    except UnsupportedRequestError:
        pass

    product: str | None = None
    try:
        product = _parse_product(normalized)
    except UnsupportedRequestError:
        pass

    missing_fields = tuple(
        name
        for name, present in (
            ("intent", intent_present),
            ("product", product is not None),
            ("amount", amount is not None),
            ("network", network is not None),
            ("beneficiary", beneficiary is not None),
        )
        if not present
    )

    complete = None
    if not missing_fields:
        complete = RequestUnderstanding().parse(normalized)

    return RequestRequirements(
        intent_present=intent_present,
        product=product,
        amount=amount,
        network=network,
        beneficiary=beneficiary,
        missing_fields=missing_fields,
        complete=complete,
    )
