"""Demo-aware account context provider.

The provider reuses the existing configuration-backed lookup and applies the
active scenario's bounded balance override. The PolicyEngine decision logic is
unchanged; it simply receives different account facts.
"""

from __future__ import annotations

from decimal import Decimal

from policy.account_context import (
    AccountContext,
    AccountType,
    DemoAccountContextProvider,
)
from switcher.demo.scenarios import get_demo_scenario_config


class DemoAwareAccountContextProvider(DemoAccountContextProvider):
    """Account context lookup that honors the active demo scenario override."""

    def get(self, beneficiary: str) -> AccountContext | None:
        account = super().get(beneficiary)
        if account is None:
            return None
        override = get_demo_scenario_config().account_balance_override
        if override is None:
            return account
        return account.model_copy(update={"balance": Decimal(override)})
