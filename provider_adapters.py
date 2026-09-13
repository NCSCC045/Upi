from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ProviderExecutionError(Exception):
    """Raised when a simulated provider cannot execute a transaction."""


@dataclass(frozen=True)
class ProviderCapabilities:
    currencies: frozenset[str]
    transaction_types: frozenset[str]
    account_types: frozenset[str]


@dataclass(frozen=True)
class ProviderExecutionResult:
    provider: str
    status: str
    provider_transaction_reference: str
    message: str


def normalize_account_type(account_type: str) -> str:
    normalized = account_type.strip().lower()
    if normalized.startswith("simulated_"):
        normalized = normalized.removeprefix("simulated_")
    return normalized


class ProviderAdapter(ABC):
    provider: str
    capabilities: ProviderCapabilities

    def is_eligible(self, account: Any, currency: str, transaction_type: str) -> bool:
        return (
            normalize_account_type(account.account_type) in self.capabilities.account_types
            and currency.upper() in self.capabilities.currencies
            and transaction_type.lower() in self.capabilities.transaction_types
        )

    @abstractmethod
    def execute(
        self,
        *,
        account: Any,
        amount: float,
        currency: str,
        recipient_reference: str,
        transaction_type: str,
    ) -> ProviderExecutionResult:
        raise NotImplementedError


class SimulatedProviderAdapter(ProviderAdapter):
    def __init__(
        self,
        provider: str,
        currencies: set[str],
        transaction_types: set[str],
        account_types: set[str],
    ):
        self.provider = provider
        self.capabilities = ProviderCapabilities(
            currencies=frozenset(currency.upper() for currency in currencies),
            transaction_types=frozenset(value.lower() for value in transaction_types),
            account_types=frozenset(normalize_account_type(value) for value in account_types),
        )

    def execute(
        self,
        *,
        account: Any,
        amount: float,
        currency: str,
        recipient_reference: str,
        transaction_type: str,
    ) -> ProviderExecutionResult:
        return ProviderExecutionResult(
            provider=self.provider,
            status="simulated_success",
            provider_transaction_reference=f"SIM-{self.provider.upper()}-{account.id}-{recipient_reference}",
            message="Simulated provider execution succeeded",
        )
