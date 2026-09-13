from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import PaymentAccount
from provider_adapters import normalize_account_type
from provider_registry import provider_registry


ELIGIBLE_ACCOUNT_STATUSES = {"active"}


def select_payment_route(
    db: Session,
    identity_id: int,
    provider: str | None = None,
    account_type: str | None = None,
    currency: str = "INR",
    transaction_type: str = "payment",
):
    normalized_provider = provider.strip().lower() if provider else None
    normalized_account_type = normalize_account_type(account_type) if account_type else None
    normalized_currency = currency.upper()
    normalized_transaction_type = transaction_type.lower()

    accounts = db.query(PaymentAccount).filter(
        PaymentAccount.identity_id == identity_id,
        PaymentAccount.status.in_(ELIGIBLE_ACCOUNT_STATUSES),
    ).order_by(PaymentAccount.priority.asc(), PaymentAccount.id.asc()).all()

    eligible_accounts = []
    for account in accounts:
        if normalized_provider and account.provider.strip().lower() != normalized_provider:
            continue
        if normalized_account_type and normalize_account_type(account.account_type) != normalized_account_type:
            continue

        adapter = provider_registry.get(account.provider)
        if adapter and adapter.is_eligible(account, normalized_currency, normalized_transaction_type):
            eligible_accounts.append(account)

    if not eligible_accounts:
        raise HTTPException(status_code=400, detail="No eligible payment account found for this identity")

    return eligible_accounts[0]
