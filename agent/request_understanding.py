"""Convert a natural-language transaction request into a validated AgentRequest.

This boundary is deliberately small and deterministic. Its only responsibility
is understanding WHAT the user requested. It never selects a vendor, never
checks policy, never routes, never calls a vendor, and never executes anything.

The parser can be replaced later by an LLM structured-extraction step without
changing AgentRuntime or the execution architecture, as long as the contract
``parse(text) -> AgentRequest`` is preserved.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from agent.runtime.service import AgentRequest


class UnsupportedRequestError(ValueError):
    """Raised when a natural-language request cannot be parsed safely."""


# Canonical intent for the supported transaction type.
DEFAULT_INTENT = "airtime_purchase"

# Supported transaction vocabulary. The parser matches these case-insensitively
# and rejects anything outside this set rather than guessing.
_SUPPORTED_PRODUCTS = ("airtime",)
_SUPPORTED_NETWORKS = ("mtn",)

# Amount: optional currency symbol, digits with optional thousands separators,
# optional two-decimal fraction. Rejects empty, zero, and negative values.
#
# The grouped alternative requires at least one ",ddd" group so it can never
# partially match an ungrouped number. The ungrouped alternative uses \d+ so
# the complete number is always captured (no 1-3 digit truncation). The
# lookbehind/lookahead guards prevent the pattern from matching a fragment of
# a longer digit run, and the optional sign makes negative amounts visible so
# they can be rejected instead of silently reinterpreted as positive.
_AMOUNT_RE = re.compile(
    r"(?<![\d,])(?P<neg>-)?\s*"
    r"(?:₦|NGN\s*|n\s*|\$)?\s*"
    r"(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"(?![\d,])"
)

# Beneficiary: a run of digits that is long enough to be a real phone number
# for this demo. We do not attempt broad Nigerian number validation; we only
# require a non-trivial digit run so we do not accidentally capture a stray
# number such as a quantity.
_BENEFICIARY_RE = re.compile(r"\b(?P<beneficiary>\d{7,})\b")

# Network token: a bare alphabetic token, normalized to upper case.
_NETWORK_RE = re.compile(r"\b(?P<network>[A-Za-z]{2,})\b")

# Product token: airtime/data/etc. Only airtime is supported in this milestone.
_PRODUCT_RE = re.compile(r"\b(?P<product>airtime|data)\b", flags=re.IGNORECASE)

# Verbs that introduce a purchase. The parser is intentionally lenient about
# surrounding words (please, kindl, can you, etc.) but strict about structure.
_PURCHASE_VERB_RE = re.compile(
    r"\b(buy|purchase|get|order|send)\b",
    flags=re.IGNORECASE,
)


def _parse_amount(text: str, beneficiary_span: tuple[int, int]) -> Decimal:
    """Extract and normalize the amount, rejecting invalid values.

    ``beneficiary_span`` is the span of the beneficiary digit run so that the
    phone number itself is never reinterpreted as an amount when no real
    amount is present (for example "Buy MTN airtime for 08030000001").
    """
    beneficiary_start, beneficiary_end = beneficiary_span

    for match in _AMOUNT_RE.finditer(text):
        start, end = match.span("amount")
        if start < beneficiary_end and beneficiary_start < end:
            # This digit run is the beneficiary, not an amount.
            continue

        if match.group("neg") is not None:
            raise UnsupportedRequestError(
                "Negative amounts are not supported in monetary requests"
            )

        raw = match.group("amount").replace(",", "")
        try:
            amount = Decimal(raw)
        except InvalidOperation as error:
            raise UnsupportedRequestError("Amount is not a valid number") from error

        if amount <= 0:
            raise UnsupportedRequestError("Amount must be greater than zero")

        return amount.quantize(Decimal("0.01"))

    raise UnsupportedRequestError("Could not find an amount in the request")


def _parse_beneficiary(text: str) -> tuple[str, tuple[int, int]]:
    """Extract the beneficiary digit run and its span within ``text``."""
    match = _BENEFICIARY_RE.search(text)
    if match is None:
        raise UnsupportedRequestError("Could not find a beneficiary in the request")
    return match.group("beneficiary"), match.span("beneficiary")


def _parse_network(text: str) -> str:
    """Extract and normalize the network token."""
    for match in _NETWORK_RE.finditer(text):
        token = match.group("network").upper()
        if token in {n.upper() for n in _SUPPORTED_NETWORKS}:
            return token
    raise UnsupportedRequestError("Could not find a supported network in the request")


def _parse_product(text: str) -> str:
    """Extract and normalize the product type, rejecting unsupported types."""
    match = _PRODUCT_RE.search(text)
    if match is None:
        raise UnsupportedRequestError("Could not find a supported product in the request")
    product = match.group("product").lower()
    if product not in _SUPPORTED_PRODUCTS:
        raise UnsupportedRequestError(f"Unsupported product type: {product}")
    return product


def _require_purchase_intent(text: str) -> None:
    """Reject requests that do not clearly describe a purchase."""
    if _PURCHASE_VERB_RE.search(text) is None:
        raise UnsupportedRequestError("Request does not describe a purchase")


class RequestUnderstanding:
    """Deterministic natural-language to AgentRequest boundary.

    The parser is side-effect free: ``parse`` never touches the network,
    vendors, policy, routing, persistence, or MCP layers.
    """

    def __init__(self, intent: str = DEFAULT_INTENT) -> None:
        self._intent = intent

    def parse(self, text: str) -> AgentRequest:
        """Parse ``text`` into a validated :class:`AgentRequest`.

        Raises :class:`UnsupportedRequestError` for malformed or unsupported
        input rather than guessing missing fields.
        """
        if not isinstance(text, str):
            raise UnsupportedRequestError("Request text must be a string")

        normalized = text.strip()
        if not normalized:
            raise UnsupportedRequestError("Request text is empty")

        _require_purchase_intent(normalized)

        beneficiary, beneficiary_span = _parse_beneficiary(normalized)
        amount = _parse_amount(normalized, beneficiary_span)
        network = _parse_network(normalized)
        product = _parse_product(normalized)

        return AgentRequest(
            intent=self._intent,
            service_type=product,
            product_type=product,
            network=network,
            beneficiary=beneficiary,
            amount=amount,
        )


def parse_request(text: str) -> AgentRequest:
    """Module-level convenience wrapper around :class:`RequestUnderstanding`."""
    return RequestUnderstanding().parse(text)