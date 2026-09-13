from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    name: str
    email: EmailStr


class PaymentAccountCreate(BaseModel):
    provider: str
    account_type: str
    account_reference: str
    priority: int = Field(default=1, ge=1)


class PaymentAccountResponse(BaseModel):
    id: int
    provider: str
    account_type: str
    account_reference: str
    status: str
    priority: int


class RoutePaymentRequest(BaseModel):
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    recipient_reference: str = Field(min_length=1)
    provider: str | None = Field(default=None, min_length=1)
    account_type: str | None = Field(default=None, min_length=1)
    transaction_type: str = Field(default="payment", min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        currency = value.upper()
        if not currency.isalpha():
            raise ValueError("currency must contain only letters")
        return currency


class AuthenticationMethodCreate(BaseModel):
    method_type: Literal["phone", "pin", "nfc", "wearable", "biometric"]
    label: str
    credential_reference: str


class AuthenticationMethodResponse(BaseModel):
    id: int
    method_type: str
    label: str
    credential_reference: str | None
    status: str


class PaymentRequestCreate(BaseModel):
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    recipient_reference: str = Field(min_length=1)
    description: str | None = None
    payment_account_id: int = Field(gt=0)
    authentication_method_id: int = Field(gt=0)
    expires_at: datetime | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        currency = value.upper()
        if not currency.isalpha():
            raise ValueError("currency must contain only letters")
        return currency


class PaymentRequestResponse(BaseModel):
    id: int
    amount: float
    currency: str
    recipient_reference: str
    description: str | None
    payment_account_id: int
    authentication_method_id: int
    status: str
    created_at: datetime
    authorized_at: datetime | None
    expires_at: datetime


class AlternativeDeviceCreate(BaseModel):
    device_type: Literal["nfc", "wearable", "security_key"]
    device_label: str = Field(min_length=1)
    device_reference: str = Field(min_length=1)


class AlternativeDeviceResponse(BaseModel):
    id: int
    device_type: str
    device_label: str
    device_reference: str
    status: str
    created_at: datetime
    last_used_at: datetime | None


class OfflinePaymentRequestCreate(BaseModel):
    amount: float = Field(gt=0)
    currency: Literal["INR"]
    recipient_reference: str = Field(min_length=1)
    description: str | None = None
    device_id: int = Field(gt=0)
    transaction_nonce: str = Field(min_length=1)
    expires_at: datetime | None = None


class OfflinePaymentRequestResponse(BaseModel):
    id: int
    amount: float
    currency: str
    recipient_reference: str
    description: str | None
    device_id: int
    transaction_nonce: str
    status: str
    created_at: datetime
    expires_at: datetime


