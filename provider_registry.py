from provider_adapters import ProviderAdapter, SimulatedProviderAdapter


class ProviderRegistry:
    def __init__(self):
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters[adapter.provider.strip().lower()] = adapter

    def get(self, provider: str) -> ProviderAdapter | None:
        return self._adapters.get(provider.strip().lower())

    def all(self) -> list[ProviderAdapter]:
        return list(self._adapters.values())


provider_registry = ProviderRegistry()

for _adapter in (
    SimulatedProviderAdapter("UPI", {"INR"}, {"payment", "transfer"}, {"upi"}),
    SimulatedProviderAdapter("Wallet", {"INR", "USD", "EUR"}, {"payment", "transfer"}, {"wallet"}),
    SimulatedProviderAdapter("Bank", {"INR", "USD", "EUR", "GBP"}, {"payment", "transfer"}, {"bank", "bank_account"}),
    SimulatedProviderAdapter("Card", {"INR", "USD", "EUR", "GBP"}, {"payment"}, {"card"}),
):
    provider_registry.register(_adapter)
