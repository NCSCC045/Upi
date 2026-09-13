from fastapi.testclient import TestClient

from database import SessionLocal
from main import app
from models import PaymentAccount, Transaction, UniversalIdentity


client = TestClient(app)


def create_identity(email_prefix: str):
    email = f"{email_prefix}_{__import__('uuid').uuid4().hex[:8]}@example.com"
    response = client.post("/register", json={"name": "Ledger Test", "email": email})
    assert response.status_code == 200, response.text
    return response.json()["universal_payment_identity"]


def create_account(upi_id: str, provider: str, account_reference: str, priority: int = 1, status: str = "active"):
    response = client.post(
        f"/identity/{upi_id}/payment-accounts",
        json={
            "provider": provider,
            "account_type": "simulated_" + provider.lower(),
            "account_reference": account_reference,
            "priority": priority,
        },
    )
    assert response.status_code == 200, response.text
    if status != "active":
        db = SessionLocal()
        try:
            identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
            account = db.query(PaymentAccount).filter(
                PaymentAccount.identity_id == identity.id,
                PaymentAccount.account_reference == account_reference,
            ).first()
            account.status = status
            db.commit()
        finally:
            db.close()
    return response.json()


def test_route_payment_creates_transaction_record():
    upi_id = create_identity("ledger_create")
    create_account(upi_id, "UPI", "UPI-LEDGER-001", priority=1)
    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 500, "currency": "INR", "recipient_reference": "merchant_ledger_1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["transaction_id"]
    transactions = client.get(f"/identity/{upi_id}/transactions")
    assert transactions.status_code == 200, transactions.text
    items = transactions.json()
    assert any(item["recipient_reference"] == "merchant_ledger_1" for item in items)


def test_get_transactions_returns_only_identity_records():
    upi_id = create_identity("ledger_only_identity")
    create_account(upi_id, "Wallet", "WALLET-ONLY-001", priority=2)
    other_upi = create_identity("ledger_other_identity")
    create_account(other_upi, "Bank", "BANK-OTHER-001", priority=1)

    client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 75, "currency": "INR", "recipient_reference": "merchant_ledger_2"},
    )
    client.post(
        f"/identity/{other_upi}/route-payment",
        json={"amount": 90, "currency": "INR", "recipient_reference": "merchant_ledger_3"},
    )

    response = client.get(f"/identity/{upi_id}/transactions")
    assert response.status_code == 200, response.text
    items = response.json()
    assert all(item["recipient_reference"] != "merchant_ledger_3" for item in items)
    assert any(item["recipient_reference"] == "merchant_ledger_2" for item in items)


def test_no_duplicate_transaction_on_repeat_route_request():
    upi_id = create_identity("ledger_duplicate")
    create_account(upi_id, "UPI", "UPI-DUP-001", priority=1)
    request_body = {"amount": 125, "currency": "INR", "recipient_reference": "merchant_duplicate"}
    first = client.post(f"/identity/{upi_id}/route-payment", json=request_body)
    second = client.post(f"/identity/{upi_id}/route-payment", json=request_body)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    transactions = client.get(f"/identity/{upi_id}/transactions")
    count = sum(1 for item in transactions.json() if item["recipient_reference"] == "merchant_duplicate")
    assert count == 2


def test_no_transaction_written_when_route_fails_for_missing_eligible_account():
    upi_id = create_identity("ledger_no_eligible")
    create_account(upi_id, "UPI", "UPI-FAILED-001", priority=1, status="inactive")
    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 40, "currency": "INR", "recipient_reference": "merchant_failed"},
    )
    assert response.status_code == 400, response.text
    transactions = client.get(f"/identity/{upi_id}/transactions")
    assert transactions.status_code == 200, transactions.text
    assert transactions.json() == []


def test_invalid_identity_for_transaction_history():
    response = client.get("/identity/INVALID-UPI/transactions")
    assert response.status_code == 404, response.text
