# Universal Payment Identity

Universal Payment Identity is a FastAPI prototype for linking one universal payment identity to multiple payment accounts, authentication methods, devices, and provider adapters.

The service demonstrates payment-account routing, payment authorization, offline payment requests, transaction recording, idempotency protection, rate limiting, and a lightweight security/risk decision engine.

## Features

- Register a user and generate a universal payment identity (`UPI-...`).
- Link UPI, wallet, bank, and card payment accounts.
- Select an eligible account by provider, account type, currency, transaction type, and priority.
- Add and revoke authentication methods and alternative devices.
- Create and authorize online payment requests.
- Create and inspect device-independent offline payment requests.
- Record routed payments in a transaction ledger.
- Prevent duplicate requests with idempotency keys.
- Apply validation, identity/account status checks, local rate limits, and risk decisions.
- Expose interactive OpenAPI documentation through FastAPI.

## Architecture

```text
Client
  |
  v
FastAPI API (main.py)
  |
  +--> SQLAlchemy models and SQLite database
  +--> Payment route selection (routing.py)
  +--> Provider registry and simulated adapters
  +--> Security and risk checks
  +--> Transaction ledger
```

The default database is the local SQLite file `upi.db`. It is created automatically when the application starts. The provider adapters are simulation-only and do not move real money.

## Requirements

- Python 3.10 or newer
- Windows PowerShell, macOS/Linux shell, or another Python-compatible environment

## Setup

Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install the runtime and test dependencies:

```powershell
python -m pip install fastapi uvicorn sqlalchemy "pydantic[email]" pytest httpx
```

On macOS or Linux, activate the environment with:

```bash
source venv/bin/activate
```

## Run the API

From the project root:

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at:

- Health response: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Quick start

Register an identity:

```powershell
$identity = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/register `
  -ContentType "application/json" `
  -Body '{"name":"Asha Rao","email":"asha@example.com"}'

$identity
```

The response contains `universal_payment_identity`. Use that value as `UPI_ID` in subsequent requests.

Add a payment account:

```powershell
$UPI_ID = $identity.universal_payment_identity

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/identity/$UPI_ID/payment-accounts" `
  -ContentType "application/json" `
  -Body '{"provider":"UPI","account_type":"upi","account_reference":"demo@upi","priority":1}'
```

Route a simulated payment:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/identity/$UPI_ID/route-payment" `
  -Headers @{ "Idempotency-Key" = "demo-payment-001" } `
  -ContentType "application/json" `
  -Body '{"amount":125.50,"currency":"INR","recipient_reference":"merchant-demo","transaction_type":"payment","idempotency_key":"demo-payment-001"}'
```

The response identifies the selected provider, simulated provider reference, status, and transaction ID.

## API reference

The complete request and response schemas are available at `/docs`. The main routes are:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/` | Service status |
| `POST` | `/register` | Create a user and universal payment identity |
| `GET` | `/identity/{upi_id}` | Get identity details |
| `GET/POST/DELETE` | `/identity/{upi_id}/authentication-methods` | Manage authentication methods |
| `GET/POST/DELETE` | `/identity/{upi_id}/devices` | Manage alternative devices |
| `GET/POST` | `/identity/{upi_id}/payment-accounts` | Manage linked payment accounts |
| `POST` | `/identity/{upi_id}/route-payment` | Select an account and execute a simulated payment |
| `GET` | `/identity/{upi_id}/transactions` | List the identity's transaction ledger |
| `GET/POST` | `/identity/{upi_id}/payment-requests` | Create and list authorization requests |
| `POST` | `/identity/{upi_id}/payment-requests/{payment_request_id}/authorize` | Authorize a pending request |
| `POST` | `/identity/{upi_id}/offline-payment-requests` | Create an offline payment request |
| `GET` | `/identity/{upi_id}/offline-payment-requests/{payment_request_id}` | Inspect an offline request |

## Providers and routing

The prototype registers these simulated providers:

| Provider | Currencies | Transaction types | Account types |
| --- | --- | --- | --- |
| `UPI` | `INR` | `payment`, `transfer` | `upi` |
| `Wallet` | `INR`, `USD`, `EUR` | `payment`, `transfer` | `wallet` |
| `Bank` | `INR`, `USD`, `EUR`, `GBP` | `payment`, `transfer` | `bank`, `bank_account` |
| `Card` | `INR`, `USD`, `EUR`, `GBP` | `payment` | `card` |

Routing considers active accounts first, then filters by the requested provider, account type, currency, and transaction type. Among eligible accounts, the lowest priority number is selected.

## Security behavior

The prototype applies the following controls before recording a transaction:

- Active identity and payment-account checks
- Supported currency and positive amount validation
- Expiration checks for payment requests and devices
- Authentication-method and device status checks
- Recipient activity and high-value payment risk scoring
- Local in-memory rate limits
- Idempotency-key duplicate detection

This is a development prototype. It does not provide production-grade authentication, cryptographic credential storage, distributed rate limiting, secrets management, or real payment settlement.

## Run tests

```powershell
python -m pytest -q
```

The test suite covers routing priority and fallback, API validation, authorization, transaction ledger behavior, provider failures, idempotency, offline requests, and security/risk decisions.

## Project structure

```text
main.py                 FastAPI application and endpoint handlers
models.py               SQLAlchemy persistence models
schemas.py              Pydantic request and response schemas
database.py             Database engine, sessions, and migrations
routing.py              Payment-account selection logic
provider_adapters.py    Provider adapter interface and simulations
provider_registry.py    Registered simulated providers
TECHNICAL_SPEC.md       Detailed architecture and implementation specification
tests/                  Automated test suite
```

## License

No license has been specified for this prototype.