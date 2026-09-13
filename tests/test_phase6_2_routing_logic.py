from fastapi.testclient import TestClient

from database import SessionLocal
from main import app, select_payment_route
from models import PaymentAccount, UniversalIdentity


client = TestClient(app)


def create_identity_for_test(email_prefix: str):
    email = f"{email_prefix}_{__import__('uuid').uuid4().hex[:8]}@example.com"
    response = client.post("/register", json={"name": "Routing Test", "email": email})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["universal_payment_identity"]


def test_selects_highest_priority_active_account():
    upi_id = create_identity_for_test("priority_1")
    db = SessionLocal()
    try:
        identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
        db.add_all([
            PaymentAccount(identity_id=identity.id, provider="Wallet", account_type="wallet", account_reference="WALLET-2", status="active", priority=2),
            PaymentAccount(identity_id=identity.id, provider="UPI", account_type="upi", account_reference="UPI-1", status="active", priority=1),
        ])
        db.commit()
        selected = select_payment_route(db, identity.id)
        assert selected.account_reference == "UPI-1"
        assert selected.provider == "UPI"
    finally:
        db.close()


def test_selects_next_priority_when_top_account_is_inactive():
    upi_id = create_identity_for_test("fallback")
    db = SessionLocal()
    try:
        identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
        db.add_all([
            PaymentAccount(identity_id=identity.id, provider="UPI", account_type="upi", account_reference="UPI-PRIMARY", status="inactive", priority=1),
            PaymentAccount(identity_id=identity.id, provider="Wallet", account_type="wallet", account_reference="WALLET-SECONDARY", status="active", priority=2),
        ])
        db.commit()
        selected = select_payment_route(db, identity.id)
        assert selected.account_reference == "WALLET-SECONDARY"
        assert selected.provider == "Wallet"
    finally:
        db.close()


def test_raises_when_no_eligible_account_exists():
    upi_id = create_identity_for_test("no_eligible")
    db = SessionLocal()
    try:
        identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
        db.add_all([
            PaymentAccount(identity_id=identity.id, provider="UPI", account_type="upi", account_reference="UPI-DISABLED", status="revoked", priority=1),
            PaymentAccount(identity_id=identity.id, provider="Wallet", account_type="wallet", account_reference="WALLET-LOCKED", status="inactive", priority=2),
        ])
        db.commit()
        try:
            select_payment_route(db, identity.id)
            assert False, "Expected an error when no active eligible account exists"
        except Exception as exc:
            assert "No eligible payment account" in str(exc)
    finally:
        db.close()


def test_does_not_select_account_from_other_identity():
    upi_id = create_identity_for_test("foreign")
    other_upi_id = create_identity_for_test("foreign_other")
    db = SessionLocal()
    try:
        identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == upi_id).first()
        other_identity = db.query(UniversalIdentity).filter(UniversalIdentity.identity_id == other_upi_id).first()
        db.add_all([
            PaymentAccount(identity_id=identity.id, provider="UPI", account_type="upi", account_reference="OWN-ACCOUNT", status="active", priority=1),
            PaymentAccount(identity_id=other_identity.id, provider="Bank", account_type="bank", account_reference="OTHER-BANK", status="active", priority=1),
        ])
        db.commit()
        selected = select_payment_route(db, identity.id)
        assert selected.account_reference == "OWN-ACCOUNT"
        assert selected.identity_id == identity.id
    finally:
        db.close()
