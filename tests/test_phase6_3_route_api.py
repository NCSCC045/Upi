from fastapi.testclient import TestClient

from database import SessionLocal
from main import app
from models import PaymentAccount, UniversalIdentity


client = TestClient(app)


def create_identity(email_prefix: str):
    email = f"{email_prefix}_{__import__('uuid').uuid4().hex[:8]}@example.com"
    response = client.post("/register", json={"name": "Routing API", "email": email})
    assert response.status_code == 200, response.text
    return response.json()["universal_payment_identity"]


def create_account(upi_id: str, provider: str, account_reference: str, priority: int, status: str = "active"):
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
            account = db.query(PaymentAccount).filter(PaymentAccount.identity_id == identity.id, PaymentAccount.account_reference == account_reference).first()
            account.status = status
            db.commit()
        finally:
            db.close()


def test_valid_route_payment():
    upi_id = create_identity("route_valid")
    create_account(upi_id, "UPI", "UPI-VALID-001", 1)
    create_account(upi_id, "Wallet", "WALLET-VALID-002", 2)
    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 500, "currency": "INR", "recipient_reference": "merchant_123"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["simulation"] is True
    assert payload["selected_provider"] == "UPI"
    assert payload["selected_account"] == "UPI-VALID-001"
    assert payload["currency"] == "INR"
    assert payload["status"] == "simulated_success"


def test_invalid_identity():
    response = client.post(
        "/identity/INVALID-UPI/route-payment",
        json={"amount": 100, "currency": "INR", "recipient_reference": "merchant_456"},
    )
    assert response.status_code == 404, response.text


def test_invalid_amount():
    upi_id = create_identity("route_amount")
    create_account(upi_id, "UPI", "UPI-DATA-001", 1)
    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 0, "currency": "INR", "recipient_reference": "merchant_789"},
    )
    assert response.status_code == 422, response.text


def test_invalid_currency():
    upi_id = create_identity("route_currency")
    create_account(upi_id, "UPI", "UPI-CURR-001", 1)
    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 250, "currency": "ZZZ", "recipient_reference": "merchant_aaa"},
    )
    assert response.status_code == 400, response.text
    assert "Unsupported currency" in response.json()["detail"]


def test_no_active_account():
    upi_id = create_identity("route_no_active")
    create_account(upi_id, "UPI", "UPI-INACTIVE-001", 1, status="inactive")
    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 300, "currency": "INR", "recipient_reference": "merchant_bbb"},
    )
    assert response.status_code == 400, response.text
    assert "No eligible payment account" in response.json()["detail"]


def test_correct_priority_selection():
    upi_id = create_identity("route_priority")
    create_account(upi_id, "UPI", "UPI-PRIMARY-1", 1)
    create_account(upi_id, "Wallet", "WALLET-PRIMARY-2", 2)
    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 150, "currency": "INR", "recipient_reference": "merchant_ccc"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["selected_account"] == "UPI-PRIMARY-1"
