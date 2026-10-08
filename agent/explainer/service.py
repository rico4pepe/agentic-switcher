"""Explain authoritative transaction outcomes without executing actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.explainer.templates import (
    terminal_claim_in,
    transaction_description,
    useful_message,
    vendor_name,
)

if TYPE_CHECKING:
    from agent.runtime.service import AgentResult


class TransactionExplainer:
    """Convert a structured result into a deterministic user-facing string."""

    def explain(self, result: AgentResult) -> str:
        description = transaction_description(result)

        if result.status == "success":
            vendor = vendor_name(result.vendor_code)
            through_vendor = f" through {vendor}" if vendor else ""
            explanation = (
                f"Your {description} was completed successfully{through_vendor}."
            )
            detail = useful_message(
                result.message,
                generic="Transaction completed successfully",
            )
            if detail:
                explanation += f" {detail}"
            return explanation

        if result.status == "denied" or result.action == "deny":
            reason = (result.reason or "").strip() or result.message.strip()
            if reason:
                return f"I couldn't complete your {description}. Reason: {reason}."
            return f"I couldn't complete your {description}; the request was denied."

        if result.status == "failed":
            detail = result.message.strip() or (result.reason or "").strip()
            if detail:
                return f"Your {description} could not be completed. {detail}"
            return f"Your {description} could not be completed."

        if result.status == "unknown":
            explanation = (
                "The transaction could not be confirmed yet. "
                "Its status is still uncertain."
            )
            detail = useful_message(
                result.message,
                generic="Transaction outcome is unknown",
            )
            if detail and not terminal_claim_in(detail):
                explanation += f" {detail}"
            elif result.reason and not terminal_claim_in(result.reason):
                explanation += f" Details: {result.reason.strip()}."
            return explanation

        status = result.status.replace("_", " ")
        return f"Your {description} is currently {status}."
