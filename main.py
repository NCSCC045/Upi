from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import uuid

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import (
    Base,
    SessionLocal,
    engine,
    migrate_authentication_methods,
    migrate_payment_account_priority,
    migrate_transaction_idempotency_key,
    migrate_transaction_type,
)
from models import (
    AlternativeDevice,
    AuthenticationMethod,
    OfflinePaymentRequest,
    PaymentAccount,
    PaymentRequest,
    Transaction,
    UniversalIdentity,
    User,
)
from schemas import (
    AuthenticationMethodCreate,
    AlternativeDeviceCreate,
    OfflinePaymentRequestCreate,
    PaymentAccountCreate,
    PaymentRequestCreate,
    RoutePaymentRequest,
    UserCreate,
)
from provider_adapters import ProviderExecutionError
from provider_registry import provider_registry
from routing import select_payment_route

Base.metadata.create_all(bind=engine)
migrate_authentication_methods()
migrate_payment_account_priority()
migrate_transaction_idempotency_key()
migrate_transaction_type()

app = FastAPI(
    title="Universal Payment Identity",
    description="A secure payment identity and interoperability platform",
    version="1.0.0"
)

SUPPORTED_CURRENCIES = {"INR", "USD", "EUR", "GBP"}
RATE_LIMIT_BUCKETS = defaultdict(deque)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enforce_local_rate_limit(identity_id: int, action: str, limit: int = 6, window_seconds: int = 300):
    bucket = RATE_LIMIT_BUCKETS[(identity_id, action)]
    now = utc_now()
    window = timedelta(seconds=window_seconds)

    while bucket and (now - bucket[0]) > window:
        bucket.popleft()

    if len(bucket) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Too many {action} attempts for this identity; please wait before retrying",
        )

    bucket.append(now)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_transaction_record(
    db: Session,
    identity_id: int,
    payment_account_id: int,
    amount: float,
    currency: str,
    recipient_reference: str,
    request_reference: str | None = None,
    idempotency_key: str | None = None,
    transaction_type: str = "payment",
    status: str = "simulated_success",
):
    if request_reference:
        existing = db.query(Transaction).filter(
            Transaction.request_reference == request_reference
        ).first()
        if existing:
            return existing

    if idempotency_key:
        existing = db.query(Transaction).filter(
            Transaction.idempotency_key == idempotency_key
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Idempotency key already used")

    transaction = Transaction(
        identity_id=identity_id,
        payment_account_id=payment_account_id,
        amount=amount,
        currency=currency,
        recipient_reference=recipient_reference,
        transaction_type=transaction_type,
        status=status,
        request_reference=request_reference or f"ROUTE-{uuid.uuid4().hex[:12].upper()}",
        idempotency_key=idempotency_key,
    )
    db.add(transaction)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            raise HTTPException(status_code=409, detail="Idempotency key already used")
        raise
    db.refresh(transaction)
    return transaction


def evaluate_risk_for_transaction(db: Session, identity_id: int, amount: float, recipient_reference: str):
    allowed, _, _, reasons = evaluate_security_decision(
        db,
        identity_id=identity_id,
        amount=amount,
        currency="INR",
        recipient_reference=recipient_reference,
    )
    return allowed, reasons


def evaluate_security_decision(
    db: Session,
    identity_id: int,
    amount: float,
    currency: str,
    recipient_reference: str,
    identity_status: str | None = None,
    account_status: str | None = None,
    auth_status: str | None = None,
    device_status: str | None = None,
    expires_at: datetime | None = None,
):
    reasons = []
    score = 0

    if amount is None or amount <= 0:
        score += 80
        reasons.append("amount is invalid")
    elif amount >= 10000:
        score += 60
        reasons.append("amount exceeds high-value threshold")

    normalized_currency = (currency or "").upper()
    if not normalized_currency or normalized_currency not in SUPPORTED_CURRENCIES:
        score += 50
        reasons.append("currency is unsupported or invalid")

    if identity_status and identity_status != "active":
        score += 80
        reasons.append("identity is not active")

    if account_status and account_status != "active":
        score += 70
        reasons.append("payment account is not active")

    if auth_status and auth_status != "active":
        score += 60
        reasons.append("authentication method is not active")

    if device_status and device_status != "active":
        score += 65
        reasons.append("device is revoked or inactive")

    if expires_at and expires_at <= utc_now():
        score += 90
        reasons.append("request or transaction has expired")

    recent_transactions = db.query(Transaction).filter(
        Transaction.identity_id == identity_id,
        Transaction.recipient_reference == recipient_reference,
        Transaction.created_at >= utc_now() - timedelta(days=1),
    ).all()

    if recent_transactions:
        recent_count = len(recent_transactions)
        recent_total = sum(float(transaction.amount) for transaction in recent_transactions)

        if recent_count >= 3 and amount >= 2500:
            score += 40
            reasons.append("recipient velocity exceeds normal pattern")

        if recent_count >= 5 or recent_total >= 5000:
            score += 20
            reasons.append("recipient activity shows unusually high cumulative volume")

    if score >= 90:
        risk_level = "HIGH"
        decision = "DENY"
    elif score >= 35:
        risk_level = "MEDIUM"
        decision = "REVIEW"
    else:
        risk_level = "LOW"
        decision = "ALLOW"

    allowed = decision == "ALLOW"
    return allowed, risk_level, decision, reasons


@app.get("/")
def home():
    return {
        "project": "Universal Payment Identity",
        "status": "Backend is running"
    }


@app.get("/identity/{upi_id}")
def get_identity(upi_id: str, db: Session = Depends(get_db)):
    identity_record = db.query(UniversalIdentity).filter(
        UniversalIdentity.identity_id == upi_id
    ).first()

    if not identity_record:
        raise HTTPException(status_code=404, detail="Universal Payment Identity not found")

    user = db.query(User).filter(User.id == identity_record.user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "name": user.name,
        "email": user.email,
        "universal_payment_identity": identity_record.identity_id,
        "status": identity_record.status
    }


def find_identity(upi_id: str, db: Session):
    identity_record = db.query(UniversalIdentity).filter(
        UniversalIdentity.identity_id == upi_id
    ).first()

    if not identity_record:
        raise HTTPException(status_code=404, detail="Universal Payment Identity not found")

    return identity_record


@app.get("/identity/{upi_id}/authentication-methods")
def get_authentication_methods(upi_id: str, db: Session = Depends(get_db)):
    identity_record = find_identity(upi_id, db)
    methods = db.query(AuthenticationMethod).filter(
        AuthenticationMethod.identity_id == identity_record.id
    ).all()

    return [
        {
            "id": method.id,
            "method_type": method.method_type,
            "label": method.label,
            "credential_reference": method.credential_reference,
            "status": method.status
        }
        for method in methods
    ]


@app.post("/identity/{upi_id}/authentication-methods")
def create_authentication_method(
    upi_id: str,
    authentication_method: AuthenticationMethodCreate,
    db: Session = Depends(get_db)
):
    identity_record = find_identity(upi_id, db)
    if identity_record.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - identity is not active")

    if db.query(AuthenticationMethod).filter(
        AuthenticationMethod.identity_id == identity_record.id,
        AuthenticationMethod.credential_reference == authentication_method.credential_reference,
    ).first():
        raise HTTPException(status_code=409, detail="Authentication method credential already exists for this identity")

    new_method = AuthenticationMethod(
        identity_id=identity_record.id,
        method_type=authentication_method.method_type,
        label=authentication_method.label,
        credential_reference=authentication_method.credential_reference,
        status="active"
    )

    db.add(new_method)
    db.commit()
    db.refresh(new_method)

    return {
        "message": "Authentication method registered successfully",
        "id": new_method.id,
        "universal_payment_identity": identity_record.identity_id,
        "method_type": new_method.method_type,
        "label": new_method.label,
        "status": new_method.status
    }


@app.delete("/identity/{upi_id}/authentication-methods/{method_id}")
def revoke_authentication_method(
    upi_id: str,
    method_id: int,
    db: Session = Depends(get_db)
):
    identity_record = find_identity(upi_id, db)
    method = db.query(AuthenticationMethod).filter(
        AuthenticationMethod.id == method_id,
        AuthenticationMethod.identity_id == identity_record.id
    ).first()

    if not method:
        raise HTTPException(status_code=404, detail="Authentication method not found")

    method.status = "revoked"
    db.commit()

    return {
        "message": "Authentication method revoked successfully",
        "id": method.id,
        "status": method.status
    }


def alternative_device_response(device: AlternativeDevice):
    return {
        "id": device.id,
        "device_type": device.device_type,
        "device_label": device.device_label,
        "device_reference": device.device_reference,
        "status": device.status,
        "created_at": device.created_at,
        "last_used_at": device.last_used_at
    }


def offline_payment_response(payment_request: OfflinePaymentRequest):
    return {
        "id": payment_request.id,
        "amount": float(payment_request.amount),
        "currency": payment_request.currency,
        "recipient_reference": payment_request.recipient_reference,
        "description": payment_request.description,
        "device_id": payment_request.device_id,
        "transaction_nonce": payment_request.transaction_nonce,
        "status": payment_request.status,
        "created_at": payment_request.created_at,
        "expires_at": payment_request.expires_at
    }


@app.post("/identity/{upi_id}/devices")
def create_alternative_device(
    upi_id: str,
    device: AlternativeDeviceCreate,
    db: Session = Depends(get_db)
):
    identity_record = find_identity(upi_id, db)
    if identity_record.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - identity is not active")

    if db.query(AlternativeDevice).filter(
        AlternativeDevice.identity_id == identity_record.id,
        AlternativeDevice.device_reference == device.device_reference,
    ).first():
        raise HTTPException(status_code=409, detail="Alternative device reference already exists for this identity")

    new_device = AlternativeDevice(
        identity_id=identity_record.id,
        device_type=device.device_type,
        device_label=device.device_label,
        device_reference=device.device_reference,
        status="active"
    )
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    return alternative_device_response(new_device)


@app.get("/identity/{upi_id}/devices")
def get_alternative_devices(upi_id: str, db: Session = Depends(get_db)):
    identity_record = find_identity(upi_id, db)
    devices = db.query(AlternativeDevice).filter(
        AlternativeDevice.identity_id == identity_record.id
    ).all()
    return [alternative_device_response(device) for device in devices]


@app.delete("/identity/{upi_id}/devices/{device_id}")
def revoke_alternative_device(
    upi_id: str,
    device_id: int,
    db: Session = Depends(get_db)
):
    identity_record = find_identity(upi_id, db)
    device = db.query(AlternativeDevice).filter(
        AlternativeDevice.id == device_id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Alternative device not found")
    if device.identity_id != identity_record.id:
        raise HTTPException(status_code=400, detail="Device does not belong to this identity")

    device.status = "revoked"
    db.commit()
    return {
        "message": "Alternative device revoked successfully",
        "id": device.id,
        "status": device.status
    }


@app.post("/identity/{upi_id}/offline-payment-requests")
def create_offline_payment_request(
    upi_id: str,
    payment_request: OfflinePaymentRequestCreate,
    db: Session = Depends(get_db)
):
    identity_record = find_identity(upi_id, db)
    if identity_record.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - identity is not active")

    enforce_local_rate_limit(identity_record.id, "offline_payment")

    device = db.query(AlternativeDevice).filter(
        AlternativeDevice.id == payment_request.device_id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Alternative device not found")
    if device.identity_id != identity_record.id:
        raise HTTPException(status_code=400, detail="Device does not belong to this identity")
    if device.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - device is revoked or inactive")
    if payment_request.amount > 1000:
        raise HTTPException(status_code=400, detail="Offline payment limit is INR 1000")

    expires_at = payment_request.expires_at or utc_now() + timedelta(minutes=15)
    if expires_at.tzinfo:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expires_at <= utc_now():
        raise HTTPException(status_code=400, detail="Offline payment request has expired")
    if db.query(OfflinePaymentRequest).filter(
        OfflinePaymentRequest.transaction_nonce == payment_request.transaction_nonce
    ).first():
        raise HTTPException(status_code=409, detail="Transaction nonce has already been used")

    new_payment_request = OfflinePaymentRequest(
        identity_id=identity_record.id,
        device_id=device.id,
        amount=payment_request.amount,
        currency=payment_request.currency,
        recipient_reference=payment_request.recipient_reference,
        description=payment_request.description,
        transaction_nonce=payment_request.transaction_nonce,
        status="simulated_success",
        expires_at=expires_at
    )
    db.add(new_payment_request)
    device.last_used_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Transaction nonce has already been used")
    db.refresh(new_payment_request)
    return {
        "message": "Offline payment accepted for prototype simulation",
        "simulation": True,
        "real_money_transferred": False,
        "payment_request": offline_payment_response(new_payment_request)
    }


@app.get("/identity/{upi_id}/offline-payment-requests/{payment_request_id}")
def get_offline_payment_request(
    upi_id: str,
    payment_request_id: int,
    db: Session = Depends(get_db)
):
    identity_record = find_identity(upi_id, db)
    payment_request = db.query(OfflinePaymentRequest).filter(
        OfflinePaymentRequest.id == payment_request_id
    ).first()
    if not payment_request:
        raise HTTPException(status_code=404, detail="Offline payment request not found")
    if payment_request.identity_id != identity_record.id:
        raise HTTPException(status_code=400, detail="Payment request does not belong to this identity")
    return offline_payment_response(payment_request)


def find_payment_request(upi_id: str, payment_request_id: int, db: Session):
    identity_record = find_identity(upi_id, db)
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.id == payment_request_id,
        PaymentRequest.identity_id == identity_record.id
    ).first()

    if not payment_request:
        raise HTTPException(status_code=404, detail="Payment request not found")

    return identity_record, payment_request


def payment_request_response(payment_request: PaymentRequest):
    return {
        "id": payment_request.id,
        "amount": float(payment_request.amount),
        "currency": payment_request.currency,
        "recipient_reference": payment_request.recipient_reference,
        "description": payment_request.description,
        "payment_account_id": payment_request.payment_account_id,
        "authentication_method_id": payment_request.authentication_method_id,
        "status": payment_request.status,
        "created_at": payment_request.created_at,
        "authorized_at": payment_request.authorized_at,
        "expires_at": payment_request.expires_at
    }


@app.post("/identity/{upi_id}/payment-requests")
def create_payment_request(
    upi_id: str,
    payment_request: PaymentRequestCreate,
    db: Session = Depends(get_db)
):
    identity_record = find_identity(upi_id, db)
    if identity_record.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - identity is not active")

    payment_account = db.query(PaymentAccount).filter(
        PaymentAccount.id == payment_request.payment_account_id,
        PaymentAccount.identity_id == identity_record.id
    ).first()
    if not payment_account:
        raise HTTPException(
            status_code=400,
            detail="Payment account does not belong to this identity"
        )
    if payment_account.status != "active":
        raise HTTPException(status_code=400, detail="Payment account is not active")

    authentication_method = db.query(AuthenticationMethod).filter(
        AuthenticationMethod.id == payment_request.authentication_method_id,
        AuthenticationMethod.identity_id == identity_record.id
    ).first()
    if not authentication_method:
        raise HTTPException(
            status_code=400,
            detail="Authentication method does not belong to this identity"
        )
    if authentication_method.status != "active":
        raise HTTPException(status_code=400, detail="Authentication method is not active")

    expires_at = payment_request.expires_at or utc_now() + timedelta(minutes=15)
    if expires_at.tzinfo:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expires_at <= utc_now():
        raise HTTPException(status_code=422, detail="expires_at must be in the future")

    enforce_local_rate_limit(identity_record.id, "payment_request")

    new_payment_request = PaymentRequest(
        identity_id=identity_record.id,
        payment_account_id=payment_request.payment_account_id,
        authentication_method_id=payment_request.authentication_method_id,
        amount=payment_request.amount,
        currency=payment_request.currency,
        recipient_reference=payment_request.recipient_reference,
        description=payment_request.description,
        status="pending",
        expires_at=expires_at
    )
    db.add(new_payment_request)
    db.commit()
    db.refresh(new_payment_request)

    return payment_request_response(new_payment_request)


@app.get("/identity/{upi_id}/payment-requests")
def get_payment_requests(upi_id: str, db: Session = Depends(get_db)):
    identity_record = find_identity(upi_id, db)
    payment_requests = db.query(PaymentRequest).filter(
        PaymentRequest.identity_id == identity_record.id
    ).all()
    return [payment_request_response(payment_request) for payment_request in payment_requests]


@app.post("/identity/{upi_id}/payment-requests/{payment_request_id}/authorize")
def authorize_payment_request(
    upi_id: str,
    payment_request_id: int,
    db: Session = Depends(get_db)
):
    identity_record, payment_request = find_payment_request(upi_id, payment_request_id, db)
    if identity_record.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - identity is not active")

    payment_account = db.query(PaymentAccount).filter(
        PaymentAccount.id == payment_request.payment_account_id,
        PaymentAccount.identity_id == identity_record.id
    ).first()
    if not payment_account:
        raise HTTPException(
            status_code=400,
            detail="Payment account does not belong to this identity"
        )
    if payment_account.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - payment account is not active")

    authentication_method = db.query(AuthenticationMethod).filter(
        AuthenticationMethod.id == payment_request.authentication_method_id,
        AuthenticationMethod.identity_id == identity_record.id
    ).first()
    if not authentication_method:
        raise HTTPException(
            status_code=400,
            detail="Authentication method does not belong to this identity"
        )
    if authentication_method.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - authentication method is not active")
    if payment_request.status != "pending":
        raise HTTPException(status_code=409, detail="Payment request is not pending")
    if payment_request.amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")
    if payment_request.expires_at <= utc_now():
        payment_request.status = "expired"
        db.commit()
        raise HTTPException(status_code=409, detail="Payment request has expired")

    enforce_local_rate_limit(identity_record.id, "payment_authorization")

    allowed, risk_level, decision, reasons = evaluate_security_decision(
        db,
        identity_record.id,
        float(payment_request.amount),
        payment_request.currency,
        payment_request.recipient_reference,
        identity_status=identity_record.status,
        account_status=payment_account.status,
        auth_status=authentication_method.status,
        expires_at=payment_request.expires_at,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Security risk decision: {decision} ({risk_level}) - {', '.join(reasons) or 'risk rule triggered'}",
        )

    payment_request.status = "simulated_success"
    payment_request.authorized_at = utc_now()
    create_transaction_record(
        db=db,
        identity_id=identity_record.id,
        payment_account_id=payment_account.id,
        amount=float(payment_request.amount),
        currency=payment_request.currency,
        recipient_reference=payment_request.recipient_reference,
        request_reference=f"PAYREQ-{payment_request.id}",
        transaction_type="payment",
    )
    db.commit()
    db.refresh(payment_request)

    return {
        "message": "Payment request authorized for prototype simulation",
        "simulation": True,
        "real_money_transferred": False,
        "payment_account_id": payment_account.id,
        "provider": payment_account.provider,
        "payment_request": payment_request_response(payment_request)
    }


@app.get("/identity/{upi_id}/payment-accounts")
def get_payment_accounts(upi_id: str, db: Session = Depends(get_db)):
    identity_record = db.query(UniversalIdentity).filter(
        UniversalIdentity.identity_id == upi_id
    ).first()

    if not identity_record:
        raise HTTPException(status_code=404, detail="Universal Payment Identity not found")

    payment_accounts = db.query(PaymentAccount).filter(
        PaymentAccount.identity_id == identity_record.id
    ).all()

    return [
        {
            "id": account.id,
            "provider": account.provider,
            "account_type": account.account_type,
            "account_reference": account.account_reference,
            "status": account.status,
            "priority": account.priority
        }
        for account in payment_accounts
    ]


@app.post("/identity/{upi_id}/payment-accounts")
def create_payment_account(
    upi_id: str,
    payment_account: PaymentAccountCreate,
    db: Session = Depends(get_db)
):
    identity_record = db.query(UniversalIdentity).filter(
        UniversalIdentity.identity_id == upi_id
    ).first()

    if not identity_record:
        raise HTTPException(status_code=404, detail="Universal Payment Identity not found")
    if identity_record.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - identity is not active")

    if db.query(PaymentAccount).filter(
        PaymentAccount.identity_id == identity_record.id,
        PaymentAccount.account_reference == payment_account.account_reference,
    ).first():
        raise HTTPException(status_code=409, detail="Payment account reference already exists for this identity")

    new_payment_account = PaymentAccount(
        identity_id=identity_record.id,
        provider=payment_account.provider,
        account_type=payment_account.account_type,
        account_reference=payment_account.account_reference,
        status="active",
        priority=payment_account.priority
    )

    db.add(new_payment_account)
    db.commit()
    db.refresh(new_payment_account)

    return {
        "message": "Payment account linked successfully",
        "id": new_payment_account.id,
        "universal_payment_identity": identity_record.identity_id,
        "provider": new_payment_account.provider,
        "account_type": new_payment_account.account_type,
        "account_reference": new_payment_account.account_reference,
        "status": new_payment_account.status,
        "priority": new_payment_account.priority
    }


@app.post("/identity/{upi_id}/route-payment")
def route_payment(
    upi_id: str,
    route_request: RoutePaymentRequest,
    db: Session = Depends(get_db)
):
    identity_record = db.query(UniversalIdentity).filter(
        UniversalIdentity.identity_id == upi_id
    ).first()

    if not identity_record:
        raise HTTPException(status_code=404, detail="Universal Payment Identity not found")
    if identity_record.status != "active":
        raise HTTPException(status_code=403, detail="Security decision: DENY - identity is not active")

    if route_request.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    if route_request.currency.upper() not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail="Unsupported currency for prototype routing")

    if route_request.idempotency_key:
        existing = db.query(Transaction).filter(
            Transaction.idempotency_key == route_request.idempotency_key
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Idempotency key already used")

    enforce_local_rate_limit(identity_record.id, "route_payment")

    transaction_type = route_request.transaction_type.strip().lower()
    selected_account = select_payment_route(
        db,
        identity_record.id,
        provider=route_request.provider,
        account_type=route_request.account_type,
        currency=route_request.currency.upper(),
        transaction_type=transaction_type,
    )
    adapter = provider_registry.get(selected_account.provider)
    if adapter is None:
        raise HTTPException(status_code=400, detail="No eligible payment account found for this identity")

    allowed, risk_level, decision, reasons = evaluate_security_decision(
        db,
        identity_record.id,
        float(route_request.amount),
        route_request.currency.upper(),
        route_request.recipient_reference,
        identity_status=identity_record.status,
        account_status=selected_account.status,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Security risk decision: {decision} ({risk_level}) - {', '.join(reasons) or 'risk rule triggered'}",
        )

    try:
        execution = adapter.execute(
            account=selected_account,
            amount=float(route_request.amount),
            currency=route_request.currency.upper(),
            recipient_reference=route_request.recipient_reference,
            transaction_type=transaction_type,
        )
    except ProviderExecutionError as exc:
        raise HTTPException(status_code=502, detail=f"Simulated provider execution failed: {exc}") from exc

    transaction = create_transaction_record(
        db=db,
        identity_id=identity_record.id,
        payment_account_id=selected_account.id,
        amount=float(route_request.amount),
        currency=route_request.currency.upper(),
        recipient_reference=route_request.recipient_reference,
        request_reference=f"ROUTE-{uuid.uuid4().hex[:12].upper()}",
        idempotency_key=route_request.idempotency_key,
        transaction_type=transaction_type,
        status=execution.status,
    )

    return {
        "simulation": True,
        "selected_provider": selected_account.provider,
        "selected_account": selected_account.account_reference,
        "amount": float(route_request.amount),
        "currency": route_request.currency.upper(),
        "recipient_reference": route_request.recipient_reference,
        "transaction_type": transaction_type,
        "status": execution.status,
        "provider_transaction_reference": execution.provider_transaction_reference,
        "provider_message": execution.message,
        "transaction_id": transaction.transaction_id,
    }


@app.get("/identity/{upi_id}/transactions")
def get_transactions(upi_id: str, db: Session = Depends(get_db)):
    identity_record = find_identity(upi_id, db)
    transactions = db.query(Transaction).filter(
        Transaction.identity_id == identity_record.id
    ).order_by(Transaction.created_at.desc()).all()

    return [
        {
            "id": record.id,
            "transaction_id": record.transaction_id,
            "payment_account_id": record.payment_account_id,
            "amount": float(record.amount),
            "currency": record.currency,
            "recipient_reference": record.recipient_reference,
            "transaction_type": record.transaction_type,
            "status": record.status,
            "created_at": record.created_at,
            "request_reference": record.request_reference,
        }
        for record in transactions
    ]


@app.post("/register")
def register_user(user: UserCreate, db: Session = Depends(get_db)):

    existing_user = db.query(User).filter(User.email == user.email).first()

    if existing_user:
        raise HTTPException(status_code=409, detail="User with this email already exists")

    new_user = User(
        name=user.name,
        email=user.email
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    identity_id = "UPI-" + uuid.uuid4().hex[:12].upper()

    identity = UniversalIdentity(
        identity_id=identity_id,
        user_id=new_user.id,
        status="active"
    )

    db.add(identity)
    db.commit()

    return {
        "message": "User registered successfully",
        "user_id": new_user.id,
        "universal_payment_identity": identity_id,
        "status": "active"
    }