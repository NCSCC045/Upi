from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)


class UniversalIdentity(Base):
    __tablename__ = "universal_identities"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default="active")


class AuthenticationMethod(Base):
    __tablename__ = "authentication_methods"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("universal_identities.id"), nullable=False)
    method_type = Column(String, nullable=False)
    label = Column(String, nullable=False)
    credential_reference = Column(String, nullable=True)
    public_key = Column(String, nullable=True)
    status = Column(String, default="active", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    last_used_at = Column(DateTime, nullable=True)


class PaymentAccount(Base):
    __tablename__ = "payment_accounts"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("universal_identities.id"), nullable=False)
    provider = Column(String, nullable=False)
    account_type = Column(String, nullable=False)
    account_reference = Column(String, nullable=False)
    status = Column(String, default="active", nullable=False)
    priority = Column(Integer, default=1, nullable=False)


class PaymentRequest(Base):
    __tablename__ = "payment_requests"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("universal_identities.id"), nullable=False)
    payment_account_id = Column(Integer, ForeignKey("payment_accounts.id"), nullable=False)
    authentication_method_id = Column(
        Integer,
        ForeignKey("authentication_methods.id"),
        nullable=False
    )
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    recipient_reference = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    authorized_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String, unique=True, index=True, nullable=False, default=lambda: "TXN-" + __import__('uuid').uuid4().hex[:12].upper())
    identity_id = Column(Integer, ForeignKey("universal_identities.id"), nullable=False)
    payment_account_id = Column(Integer, ForeignKey("payment_accounts.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    recipient_reference = Column(String, nullable=False)
    transaction_type = Column(String, nullable=False, default="payment")
    status = Column(String, default="simulated_pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    request_reference = Column(String, unique=True, index=True, nullable=True)
    idempotency_key = Column(String, index=True, nullable=True)


class AlternativeDevice(Base):
    __tablename__ = "alternative_devices"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("universal_identities.id"), nullable=False)
    device_type = Column(String, nullable=False)
    device_label = Column(String, nullable=False)
    device_reference = Column(String, nullable=False)
    status = Column(String, default="active", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)


class OfflinePaymentRequest(Base):
    __tablename__ = "offline_payment_requests"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("universal_identities.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("alternative_devices.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    recipient_reference = Column(String, nullable=False)
    description = Column(String, nullable=True)
    transaction_nonce = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default="simulated_success", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)