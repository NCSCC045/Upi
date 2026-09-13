from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def unique_email(prefix: str) -> str:
    return f"{prefix}_{__import__('uuid').uuid4().hex[:8]}@example.com"


def create_identity(email_prefix: str = "security"):
    email = unique_email(email_prefix)
    response = client.post("/register", json={"name": "Security User", "email": email})
    assert response.status_code == 200, response.text
    return response.json()["universal_payment_identity"]


def create_account(upi_id: str, provider: str = "UPI", account_reference: str = "SEC-001"):
    response = client.post(
        f"/identity/{upi_id}/payment-accounts",
        json={
            "provider": provider,
            "account_type": "simulated_" + provider.lower(),
            "account_reference": account_reference,
            "priority": 1,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_auth_method(upi_id: str, label: str = "Security Phone"):
    from database import SessionLocal
    from models import AuthenticationMethod, UniversalIdentity

    db = SessionLocal()
    try:
        identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
        assert identity is not None
        method = AuthenticationMethod(
            identity_id=identity.id,
            method_type="phone",
            label=label,
            credential_reference="SEC-PHONE-001",
            status="active",
        )
        db.add(method)
        db.commit()
        db.refresh(method)
        return method.id
    finally:
        db.close()


def test_route_payment_rejects_reused_idempotency_key():
    upi_id = create_identity("route_replay")
    key = f"repeat-guard-{__import__('uuid').uuid4().hex[:12]}"
    create_account(upi_id, "UPI", f"UPI-REPLAY-{__import__('uuid').uuid4().hex[:8]}")

    body = {
        "amount": 250,
        "currency": "INR",
        "recipient_reference": "merchant_replay_1",
        "idempotency_key": key,
    }

    first = client.post(f"/identity/{upi_id}/route-payment", json=body)
    second = client.post(f"/identity/{upi_id}/route-payment", json=body)

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text

    transactions = client.get(f"/identity/{upi_id}/transactions")
    assert transactions.status_code == 200, transactions.text
    items = [item for item in transactions.json() if item["recipient_reference"] == "merchant_replay_1"]
    assert len(items) == 1


def test_high_risk_payment_request_is_blocked_by_security_engine():
    upi_id = create_identity("high_risk")
    account = create_account(upi_id, "Bank", f"BANK-HIGH-RISK-{__import__('uuid').uuid4().hex[:8]}")
    method_id = create_auth_method(upi_id)

    payment_response = client.post(
        f"/identity/{upi_id}/payment-requests",
        json={
            "amount": 25000,
            "currency": "INR",
            "recipient_reference": "merchant_risk_high",
            "payment_account_id": account["id"],
            "authentication_method_id": method_id,
        },
    )
    assert payment_response.status_code == 200, payment_response.text

    authorize_response = client.post(
        f"/identity/{upi_id}/payment-requests/{payment_response.json()['id']}/authorize",
    )
    assert authorize_response.status_code == 403, authorize_response.text
    assert "risk" in authorize_response.json()["detail"].lower()


def test_repeated_same_recipient_activity_triggers_risk_review():
    upi_id = create_identity("velocity_risk")
    create_account(upi_id, "Wallet", f"WALLET-VELOCITY-{__import__('uuid').uuid4().hex[:8]}")

    for idx in range(3):
        response = client.post(
            f"/identity/{upi_id}/route-payment",
            json={
                "amount": 100 + idx,
                "currency": "INR",
                "recipient_reference": "merchant_velocity_1",
            },
        )
        assert response.status_code == 200, response.text

    transactions = client.get(f"/identity/{upi_id}/transactions")
    assert transactions.status_code == 200, transactions.text
    assert sum(1 for item in transactions.json() if item["recipient_reference"] == "merchant_velocity_1") >= 3

    risk_response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={
            "amount": 4000,
            "currency": "INR",
            "recipient_reference": "merchant_velocity_1",
        },
    )
    assert risk_response.status_code == 403, risk_response.text
    assert "risk" in risk_response.json()["detail"].lower()


def test_inactive_identity_is_rejected_before_routing():
    upi_id = create_identity("inactive_identity")
    create_account(upi_id, "Bank", f"BANK-INACTIVE-{__import__('uuid').uuid4().hex[:8]}")

    from database import SessionLocal
    from models import UniversalIdentity

    db = SessionLocal()
    try:
        identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
        identity.status = "inactive"
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/identity/{upi_id}/route-payment",
        json={
            "amount": 250,
            "currency": "INR",
            "recipient_reference": "merchant_inactive_identity",
        },
    )
    assert response.status_code in {400, 403}, response.text
    assert "identity" in response.json()["detail"].lower()


def test_inactive_payment_account_is_rejected_for_authorization():
    upi_id = create_identity("inactive_account")
    account = create_account(upi_id, "Bank", f"BANK-INACTIVE-ACCOUNT-{__import__('uuid').uuid4().hex[:8]}")
    method_id = create_auth_method(upi_id)

    request_response = client.post(
        f"/identity/{upi_id}/payment-requests",
        json={
            "amount": 500,
            "currency": "INR",
            "recipient_reference": "merchant_inactive_account",
            "payment_account_id": account["id"],
            "authentication_method_id": method_id,
        },
    )
    assert request_response.status_code == 200, request_response.text

    from database import SessionLocal
    from models import PaymentAccount

    db = SessionLocal()
    try:
        payment_account = db.query(PaymentAccount).filter(PaymentAccount.id == account["id"]).first()
        payment_account.status = "inactive"
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/identity/{upi_id}/payment-requests/{request_response.json()['id']}/authorize",
    )
    assert response.status_code in {400, 403}, response.text
    assert "account" in response.json()["detail"].lower()


def test_revoked_device_is_rejected_for_offline_request():
    upi_id = create_identity("revoked_device")

    device_response = client.post(
        f"/identity/{upi_id}/devices",
        json={
            "device_type": "nfc",
            "device_label": "Office Tag",
            "device_reference": "DEVICE-REVOKED-1",
        },
    )
    assert device_response.status_code == 200, device_response.text
    device_id = device_response.json()["id"]

    revoke_response = client.delete(f"/identity/{upi_id}/devices/{device_id}")
    assert revoke_response.status_code == 200, revoke_response.text

    response = client.post(
        f"/identity/{upi_id}/offline-payment-requests",
        json={
            "amount": 250,
            "currency": "INR",
            "recipient_reference": "merchant_offline_revoked",
            "description": "Offline test",
            "device_id": device_id,
            "transaction_nonce": f"nonce-revoked-{__import__('uuid').uuid4().hex[:12]}",
        },
    )
    assert response.status_code in {400, 403}, response.text
    assert "device" in response.json()["detail"].lower()


def test_expired_payment_request_is_rejected_by_security_engine():
    upi_id = create_identity("expired_request")
    account = create_account(upi_id, "UPI", f"UPI-EXPIRED-{__import__('uuid').uuid4().hex[:8]}")
    method_id = create_auth_method(upi_id)

    from datetime import timedelta, datetime

    request_response = client.post(
        f"/identity/{upi_id}/payment-requests",
        json={
            "amount": 400,
            "currency": "INR",
            "recipient_reference": "merchant_expired_request",
            "payment_account_id": account["id"],
            "authentication_method_id": method_id,
            "expires_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
        },
    )
    assert request_response.status_code == 422, request_response.text

    request_response = client.post(
        f"/identity/{upi_id}/payment-requests",
        json={
            "amount": 400,
            "currency": "INR",
            "recipient_reference": "merchant_expired_request",
            "payment_account_id": account["id"],
            "authentication_method_id": method_id,
        },
    )
    assert request_response.status_code == 200, request_response.text

    from database import SessionLocal
    from models import PaymentRequest

    db = SessionLocal()
    try:
        payment_request = db.query(PaymentRequest).filter(PaymentRequest.id == request_response.json()["id"]).first()
        payment_request.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/identity/{upi_id}/payment-requests/{request_response.json()['id']}/authorize",
    )
    assert response.status_code in {409, 403}, response.text
    assert "expired" in response.json()["detail"].lower() or "risk" in response.json()["detail"].lower()
