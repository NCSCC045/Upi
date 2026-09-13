from fastapi.testclient import TestClient

from main import app
from database import SessionLocal
from models import AuthenticationMethod, PaymentAccount, UniversalIdentity, User


client = TestClient(app)


def unique_email(prefix: str) -> str:
    return f"{prefix}_{__import__('uuid').uuid4().hex[:8]}@example.com"


def create_user_and_identity(email_prefix: str = "phase6"):
    email = unique_email(email_prefix)
    response = client.post("/register", json={"name": "Test User", "email": email})
    assert response.status_code == 200, response.text
    payload = response.json()
    upi_id = payload["universal_payment_identity"]
    return upi_id


def create_payment_account(upi_id: str, provider: str, account_reference: str, priority: int = 1, status: str = "active"):
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
    account_payload = response.json()
    assert account_payload["status"] == status
    return account_payload


def create_authentication_method(upi_id: str, label: str = "Test Phone"):
    response = client.get(f"/identity/{upi_id}")
    assert response.status_code == 200, response.text
    db = SessionLocal()
    try:
        identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
        assert identity is not None
        method = AuthenticationMethod(
            identity_id=identity.id,
            method_type="phone",
            label=label,
            credential_reference="SIM-REF-TEST",
            status="active",
        )
        db.add(method)
        db.commit()
        db.refresh(method)
        return method.id
    finally:
        db.close()


def test_route_payment_prefers_highest_priority_active_account():
    upi_id = create_user_and_identity("route_priority")
    create_payment_account(upi_id, "Wallet", "WALLET-PRIORITY-2", priority=2)
    create_payment_account(upi_id, "UPI", "UPI-PRIORITY-1", priority=1)

    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 500, "currency": "INR", "recipient_reference": "merchant_123"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["simulation"] is True
    assert payload["selected_provider"] == "UPI"
    assert payload["selected_account"] == "UPI-PRIORITY-1"
    assert payload["amount"] == 500
    assert payload["currency"] == "INR"

    transactions = client.get(f"/identity/{upi_id}/transactions")
    assert transactions.status_code == 200, transactions.text
    txn_payload = transactions.json()
    assert any(item["recipient_reference"] == "merchant_123" for item in txn_payload)


def test_route_payment_falls_back_to_next_priority_when_current_is_inactive():
    upi_id = create_user_and_identity("route_fallback")
    preferred = create_payment_account(upi_id, "UPI", "UPI-FALLBACK-PRIMARY", priority=1)
    fallback = create_payment_account(upi_id, "Wallet", "WALLET-FALLBACK-SECONDARY", priority=2)

    db = SessionLocal()
    try:
        account = db.query(PaymentAccount).filter(PaymentAccount.id == preferred["id"]).first()
        account.status = "inactive"
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 350, "currency": "INR", "recipient_reference": "merchant_456"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["selected_provider"] == "Wallet"
    assert payload["selected_account"] == fallback["account_reference"]


def test_route_payment_rejects_missing_eligible_account():
    upi_id = create_user_and_identity("route_no_eligible")
    account_ref = f"UPI-REVOKED-{__import__('uuid').uuid4().hex[:8]}"
    create_payment_account(upi_id, "UPI", account_ref, priority=1)

    db = SessionLocal()
    try:
        account = db.query(PaymentAccount).filter(
            PaymentAccount.identity_id == db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first().id,
            PaymentAccount.account_reference == account_ref,
        ).first()
        account.status = "revoked"
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={"amount": 200, "currency": "INR", "recipient_reference": "merchant_789"},
    )
    assert response.status_code == 400, response.text
    assert "eligible" in response.json()["detail"].lower()


def test_payment_authorization_creates_transaction_record():
    upi_id = create_user_and_identity("authorize_txn")
    account = create_payment_account(upi_id, "Bank", "BANK-AUTH-1", priority=1)
    method_id = create_authentication_method(upi_id)

    payment_response = client.post(
        f"/identity/{upi_id}/payment-requests",
        json={
            "amount": 750,
            "currency": "INR",
            "recipient_reference": "merchant_auth_001",
            "payment_account_id": account["id"],
            "authentication_method_id": method_id,
        },
    )
    assert payment_response.status_code == 200, payment_response.text
    payment_payload = payment_response.json()
    request_id = payment_payload["id"]

    authorize_response = client.post(
        f"/identity/{upi_id}/payment-requests/{request_id}/authorize",
    )
    assert authorize_response.status_code == 200, authorize_response.text

    transactions = client.get(f"/identity/{upi_id}/transactions")
    assert transactions.status_code == 200, transactions.text
    txns = transactions.json()
    assert any(item["recipient_reference"] == "merchant_auth_001" for item in txns)
