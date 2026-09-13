from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from main import app, create_transaction_record
from models import Transaction
from provider_adapters import (
    ProviderExecutionError,
    ProviderExecutionResult,
    SimulatedProviderAdapter,
)
from provider_registry import provider_registry
from database import SessionLocal


client = TestClient(app)


def create_identity(prefix: str) -> str:
    response = client.post(
        "/register",
        json={"name": "Checkpoint 6", "email": f"{prefix}_{__import__('uuid').uuid4().hex}@example.com"},
    )
    assert response.status_code == 200, response.text
    return response.json()["universal_payment_identity"]


def create_account(upi_id: str, provider: str, account_type: str, priority: int) -> dict:
    response = client.post(
        f"/identity/{upi_id}/payment-accounts",
        json={
            "provider": provider,
            "account_type": account_type,
            "account_reference": f"{provider}-{__import__('uuid').uuid4().hex[:8]}",
            "priority": priority,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def route(upi_id: str, **overrides):
    body = {
        "amount": 100,
        "currency": "INR",
        "recipient_reference": f"merchant-{__import__('uuid').uuid4().hex[:8]}",
    }
    body.update(overrides)
    return client.post(f"/identity/{upi_id}/route-payment", json=body)


def test_account_type_and_currency_filter_before_priority():
    upi_id = create_identity("capability_filter")
    create_account(upi_id, "UPI", "simulated_upi", 1)
    wallet = create_account(upi_id, "Wallet", "simulated_wallet", 2)

    response = route(upi_id, account_type="wallet", currency="USD")

    assert response.status_code == 200, response.text
    assert response.json()["selected_account"] == wallet["account_reference"]


def test_provider_filter_and_transaction_type_are_persisted():
    upi_id = create_identity("provider_filter")
    account = create_account(upi_id, "Bank", "simulated_bank", 1)

    response = route(
        upi_id,
        provider="bank",
        transaction_type="transfer",
        recipient_reference="merchant-transfer",
    )

    assert response.status_code == 200, response.text
    assert response.json()["selected_provider"] == "Bank"
    assert response.json()["transaction_type"] == "transfer"

    db = SessionLocal()
    try:
        transaction = db.query(Transaction).filter(
            Transaction.payment_account_id == account["id"],
            Transaction.recipient_reference == "merchant-transfer",
        ).one()
        assert transaction.transaction_type == "transfer"
    finally:
        db.close()


def test_ineligible_statuses_are_excluded_and_no_account_keeps_400():
    upi_id = create_identity("status_filter")
    first = create_account(upi_id, "UPI", "simulated_upi", 1)
    second = create_account(upi_id, "Wallet", "simulated_wallet", 2)

    db = SessionLocal()
    try:
        for account_id in (first["id"], second["id"]):
            account = db.query(__import__("models").PaymentAccount).filter(
                __import__("models").PaymentAccount.id == account_id
            ).one()
            account.status = "revoked" if account_id == first["id"] else "closed"
        db.commit()
    finally:
        db.close()

    response = route(upi_id)

    assert response.status_code == 400
    assert "No eligible payment account" in response.json()["detail"]


class CountingAdapter(SimulatedProviderAdapter):
    def __init__(self, provider="Counting"):
        super().__init__(provider, {"INR"}, {"payment"}, {"counting"})
        self.executions = 0

    def execute(self, **kwargs):
        self.executions += 1
        return super().execute(**kwargs)


class DecliningAdapter(CountingAdapter):
    def execute(self, **kwargs):
        self.executions += 1
        return ProviderExecutionResult(
            provider=self.provider,
            status="simulated_declined",
            provider_transaction_reference="SIM-DECLINED-1",
            message="Simulated provider declined the payment",
        )


class FailingAdapter(CountingAdapter):
    def execute(self, **kwargs):
        self.executions += 1
        raise ProviderExecutionError("simulated provider unavailable")


def test_risk_denial_prevents_adapter_execution_and_ledger_write():
    adapter = CountingAdapter()
    provider_registry.register(adapter)
    try:
        upi_id = create_identity("risk_before_execute")
        create_account(upi_id, "Counting", "simulated_counting", 1)

        response = route(upi_id, amount=25000)

        assert response.status_code == 403
        assert adapter.executions == 0
        assert client.get(f"/identity/{upi_id}/transactions").json() == []
    finally:
        provider_registry._adapters.pop("counting", None)


def test_provider_decline_is_normalized_and_recorded():
    adapter = DecliningAdapter()
    provider_registry.register(adapter)
    try:
        upi_id = create_identity("provider_decline")
        create_account(upi_id, "Counting", "simulated_counting", 1)

        response = route(upi_id)

        assert response.status_code == 200
        assert response.json()["status"] == "simulated_declined"
        assert client.get(f"/identity/{upi_id}/transactions").json()[0]["status"] == "simulated_declined"
    finally:
        provider_registry._adapters.pop("counting", None)


def test_provider_failure_is_controlled_and_writes_no_transaction():
    adapter = FailingAdapter()
    provider_registry.register(adapter)
    try:
        upi_id = create_identity("provider_failure")
        create_account(upi_id, "Counting", "simulated_counting", 1)

        response = route(upi_id)

        assert response.status_code == 502
        assert client.get(f"/identity/{upi_id}/transactions").json() == []
    finally:
        provider_registry._adapters.pop("counting", None)


def test_idempotency_integrity_race_is_returned_as_409(monkeypatch):
    upi_id = create_identity("idempotency_race")
    db = SessionLocal()
    try:
        identity = db.query(__import__("models").UniversalIdentity).filter(
            __import__("models").UniversalIdentity.identity_id == upi_id
        ).one()

        def fail_commit():
            raise IntegrityError("duplicate", {}, Exception())

        monkeypatch.setattr(db, "commit", fail_commit)
        try:
            create_transaction_record(
                db=db,
                identity_id=identity.id,
                payment_account_id=1,
                amount=10,
                currency="INR",
                recipient_reference="race",
                idempotency_key="race-key",
            )
            assert False, "Expected an idempotency conflict"
        except HTTPException as exc:
            assert exc.status_code == 409
    finally:
        db.close()
