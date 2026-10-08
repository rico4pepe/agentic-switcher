"""Formatting helpers for user-facing transaction outcome explanations."""

from __future__ import annotations

from decimal import Decimal
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.runtime.service import AgentResult


def format_amount(amount: Decimal) -> str:
    """Format a monetary amount without hiding its fractional precision."""
    formatted = format(amount, ",f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return f"₦{formatted}"


def transaction_description(result: AgentResult) -> str:
    """Describe only the request facts present in the structured result."""
    product = result.product_type.replace("_", " ").replace("-", " ").lower()
    network = f"{result.network} " if result.network else ""
    return (
        f"{format_amount(result.amount)} {network}{product} purchase "
        f"for {result.beneficiary}"
    )


def vendor_name(vendor_code: str | None) -> str | None:
    """Render the actual vendor code without inferring a routing decision."""
    if vendor_code is None or not vendor_code.strip():
        return None
    known_names = {
        "vendor_a": "Vendor A",
        "vendor_b": "Vendor B",
    }
    normalized = vendor_code.strip().lower()
    return known_names.get(normalized, vendor_code.replace("_", " ").title())


def useful_message(message: str, *, generic: str) -> str | None:
    """Ignore the generic status message when the template says the same fact."""
    message = message.strip()
    if not message or message.casefold() == generic.casefold():
        return None
    return message


def terminal_claim_in(message: str) -> bool:
    """Detect terminal claims that conflict with an UNKNOWN result."""
    return re.search(
        r"\b(?:success(?:ful(?:ly)?)?|succeed(?:ed)?|fail(?:ed|ure)?|"
        r"complet(?:e|ed)|retry(?:ing)?|retries)\b",
        message,
        flags=re.IGNORECASE,
    ) is not None
