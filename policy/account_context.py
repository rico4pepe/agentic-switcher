"""Minimal account context used for deterministic transaction policy."""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AccountType(StrEnum):
    PREPAID = "PREPAID"
    POSTPAID = "POSTPAID"


class AccountContext(BaseModel):
    """The account facts required to decide whether a request may proceed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    beneficiary: str = Field(min_length=1, max_length=100)
    account_type: AccountType
    balance: Decimal = Field(ge=0)


class DemoAccountContextProvider:
    """Configuration-backed lookup for the single demonstrable account."""

    def __init__(self, contexts: tuple[AccountContext, ...] | None = None) -> None:
        if contexts is None:
            from apps.api.app.config import settings

            contexts = (
                AccountContext(
                    beneficiary=settings.demo_account_beneficiary,
                    account_type=settings.demo_account_type,
                    balance=settings.demo_account_balance,
                ),
            )
        self._contexts = {context.beneficiary: context for context in contexts}

    def get(self, beneficiary: str) -> AccountContext | None:
        return self._contexts.get(beneficiary)
