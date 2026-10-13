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
#
# Speech-to-text and dictation often insert separators inside a spoken number
# ("0803 000 0001", "080-300-00001", non-breaking spaces). The pattern therefore
# also accepts digit groups joined by a single whitespace character, hyphen, or
# non-breaking space. The separators are stripped later; no digit is ever added,
# removed, or reordered. The leading lookaround keeps a fragment of a larger
# comma-grouped number (for example an amount such as "500,000") from matching.
_BENEFICIARY_RE = re.compile(
    r"(?<![\d,])"
    r"(?P<beneficiary>\d{7,}|\d+(?:[ \t\u00a0-]\d+)+)"
    r"(?![\d,])",
)

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
    """Extract the beneficiary digit run and its span within ``text``.

    Accepts a contiguous number (``08030000001``) or digit groups joined by a
    single whitespace, hyphen, or non-breaking space (``0803 000 0001``). Only
    the separators are removed; every digit is preserved verbatim, including
    leading zeros. The returned span covers the whole (possibly separated)
    match so amount parsing never mistakes a phone fragment for the amount.
    """
    for match in _BENEFICIARY_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group("beneficiary"))
        if len(digits) >= 7:
            return digits, match.span("beneficiary")
    raise UnsupportedRequestError("Could not find a beneficiary in the request")


def _parse_network(text: str) -> str:
    """Extract and normalize the network token."""
    for match in _NETWORK_RE.finditer(text):
        token = match.group("network").upper()
        if token in {n.upper() for n in _SUPPORTED_NETWORKS}:
            return token
    raise UnsupportedRequestError("Could not find a supported network in the request")


def _infer_product_from_context(text: str) -> str | None:
    """Infer the product in context-aware ways.

    - If an explicit, supported product (other than unsupported) is mentioned,
      defer to _parse_product's strict behavior.
    - For airtime (the only supported product in this domain), infer airtime
      when the request is clearly an airtime purchase context: intent is
      present and amount is present, OR when amount+network point to airtime.
      Do not infer if 'data' appears (context is different).
    - Only infer airtime; never guess other products.
    """
    normalized = text.casefold()
    # If user explicitly mentions data, don't infer airtime
    if re.search(r"\bdata\b", normalized):
        return None
    # If there's already an airtime mention, _parse_product will find it
    if _PRODUCT_RE.search(text):
        return None
    # Infer airtime if purchase intent exists and amount exists (strong signal)
    has_intent = _PURCHASE_VERB_RE.search(text) is not None
    has_network = _NETWORK_RE.search(text) is not None
    try:
        # need beneficiary span to safely parse amount; find if beneficiary exists
        ben = None
        try:
            ben, ben_span = _parse_beneficiary(text)
        except Exception:
            ben = None
            ben_span = (0, 0)
        has_amount = False
        try:
            _parse_amount(text, ben_span) if ben is not None else False
            has_amount = True
        except Exception:
            has_amount = False
    except Exception:
        has_amount = False
    # But easier: just check patterns
    try:
        _parse_beneficiary(text)
        # has beneficiary
    except Exception:
        pass

    # Simpler: detect amount without beneficiary interference - scan for amount pattern not overlapping a long digit run
    amount_matches = list(_AMOUNT_RE.finditer(text))
    has_amount = bool(amount_matches)
    # Also if network is MTN in context of purchase intent + amount? common case
    if has_intent and has_amount:
        return "airtime"
    # Also if we have intent, network (MTN), amount - yes
    if has_intent and has_amount and has_network:
        return "airtime"
    # Another case: "Buy 5000. MTN. 080..." - amount exists, network exists, intent exists
    if has_intent and has_amount:
        return "airtime"
    # Fallback: if intent + network + beneficiary+amount might come later; but we need to be context-aware
    # For combined turns like "Buy 5000" + "MTN" + "080..." - when inspecting combined, has_intent True, has_amount True, has_network True
    if has_intent and (has_amount or has_network):  # be a bit lenient in combined context
        # Don't override if data mentioned
        if "data" in normalized:
            return None
        # Common airtime case in this domain
        return "airtime"
    return None


def _parse_product(text: str) -> str:
    """Extract and normalize the product type, rejecting unsupported types."""
    match = _PRODUCT_RE.search(text)
    if match is not None:
        product = match.group("product").lower()
        if product not in _SUPPORTED_PRODUCTS:
            raise UnsupportedRequestError(f"Unsupported product type: {product}")
        return product
    inferred = _infer_product_from_context(text)
    if inferred is not None:
        return inferred
    raise UnsupportedRequestError("Could not find a supported product in the request")


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