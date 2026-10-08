"""Deterministic policy decisions for transaction requests."""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from policy.account_context import AccountContext, AccountType, DemoAccountContextProvider


class PolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class PolicyDecision(BaseModel):
    """Structured outcome from deterministic policy evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: PolicyAction
    reason: str


class PolicyEngine:
    """Apply deterministic policy using account facts, never planner output."""

    def __init__(
        self,
        account_contexts: DemoAccountContextProvider | None = None,
    ) -> None:
        self._account_contexts = account_contexts or DemoAccountContextProvider()

    def evaluate(self, beneficiary: str, amount: Decimal) -> PolicyDecision:
        account = self._account_contexts.get(beneficiary)
        if account is None:
            return PolicyDecision(
                action=PolicyAction.DENY,
                reason="Account context not found",
            )
        if account.account_type == AccountType.PREPAID:
            if account.balance >= amount:
                return PolicyDecision(
                    action=PolicyAction.ALLOW,
                    reason="Sufficient balance",
                )
            return PolicyDecision(
                action=PolicyAction.DENY,
                reason="Insufficient balance",
            )
        return PolicyDecision(
            action=PolicyAction.DENY,
            reason="Postpaid policy is not configured",
        )


default_policy_engine = PolicyEngine()
