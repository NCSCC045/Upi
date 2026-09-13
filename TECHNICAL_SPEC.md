# Universal Payment Identity Technical Specification

Status: design baseline for the college/project prototype
Version: 0.1

## 1. Definition

A Universal Payment Identity (UPID) is a provider-neutral, revocable identifier for one payment principal. It is a stable reference that can authorize payment through many independently registered authenticators and linked payment accounts. It is not a bank account, wallet balance, phone number, card number, or authentication secret.

The phone is one authenticator. An NFC card, wearable, recovery method, and future biometric authenticator are other ways to prove control of the same UPID. A UPID service must never infer authority from possession of the identifier alone.

The system has four separate concepts:

- UPID: the logical payment identity and its lifecycle.
- Authenticator: a registered device, token, or biometric-backed key.
- Payment account: an external account or tokenized funding source.
- Payment intent: a request to pay, which becomes a provider transaction only after authorization and risk checks.

## 2. UPID format

Use a non-meaningful, opaque identifier:

`upid_01_<base32-crockford-26-character-random-value>`

For example: `upid_01_7K3M2V8Q1J4R6T9P0W5X2C8N7H`.

The random value is generated with a cryptographically secure random number generator. It contains no name, phone, email, country, bank, or sequential database ID. The `01` is a format version, not a user version. Store the canonical value normalized to lowercase; display may use uppercase. Use a unique database index and never recycle an identifier.

The format is secure because it is non-enumerable and carries no personal data. It scales because it is globally unique, short enough for QR/NFC/display use, independent of any country or provider, and versioned for future encodings. Authorization always requires a signed challenge and risk decision; knowing a UPID is never sufficient.

## 3. Identity model

An identity has a lifecycle: `pending`, `active`, `suspended`, `recovery_required`, or `closed`. The identity owner has a profile with minimal personal data and separately managed consent, audit, and recovery records.

Ownership is represented by registered public keys and successful recovery policy, not by an email address. Email can be a notification or prototype login attribute, but must not be the sole production recovery factor.

## 4. Authentication and credential model

Use asymmetric credentials wherever possible:

- Each authenticator creates a non-exportable private key in Secure Enclave, Android Keystore, WebAuthn hardware, or a secure token. The server stores only the public key, algorithm, status, and metadata.
- The server issues a short-lived nonce/challenge containing identity, authenticator, action, amount, currency, merchant, and expiration.
- The authenticator signs the canonical challenge. The server verifies the signature, nonce status, timestamp, audience, and transaction binding.
- WebAuthn/passkeys are the preferred phone/browser mechanism. NFC and wearable keys use an equivalent challenge-response protocol.
- A device session uses short-lived access tokens and rotating refresh tokens. Refresh tokens are hashed at rest and revocable.
- Biometrics unlock a local key; biometric templates stay inside the platform secure hardware. The UPID service receives a proof from the platform, never a raw biometric.

Credential states are `pending`, `active`, `lost`, `revoked`, and `replaced`. Require step-up authentication for linking accounts, changing recovery policy, high-risk payments, and adding authenticators.

## 5. Connecting authenticators to one UPID

All authenticators have an `authenticator_id`, a public key, an owner UPID, a type, and a lifecycle. Enrollment requires an already authenticated authenticator plus a one-time enrollment ceremony. The user names the device/token and can revoke it independently.

- Phone: passkey or app key, unlocked by device biometric/PIN.
- NFC card/token: contains a secure element key or token handle; it does not contain bank credentials or an unrestricted payment secret.
- Wearable: paired secure-element key, normally requiring recent phone pairing or a local PIN/biometric policy.
- Future biometric: a platform credential that signs with a hardware-protected key after local biometric verification.

The payment authorization service consumes an abstract `AuthenticatorProof`, so adding a type does not change provider adapters.

## 6. Dead-phone payment flow

This is a controlled emergency flow, not a claim that a dead phone can transmit or approve arbitrary payments.

1. Before the phone fails, the user enrolls an NFC token and sets an emergency policy.
2. The token presents its identifier and signs a merchant terminal challenge.
3. The terminal sends UPID reference, signed proof, merchant, amount, currency, device/terminal data, and a fresh terminal nonce to the payment gateway.
4. The gateway verifies the token public key, signature, expiry, nonce, token status, and emergency policy.
5. The risk engine evaluates amount, velocity, merchant, geography, token history, and whether online authorization is available.
6. If online, the orchestrator creates a payment intent, selects an eligible linked account, and requests provider authorization.
7. The gateway returns approved, declined, or pending. The terminal displays a receipt/reference; it does not receive bank credentials.
8. If offline emergency mode is enabled, the terminal records a signed, single-use authorization envelope within the token and policy limits, then queues it for reconciliation.
9. The user can later use any trusted authenticator to review, confirm, dispute, or revoke the token.

If the phone is dead and no pre-enrolled token or merchant-supported emergency path exists, the payment must be declined. The design must not rely on SMS to a dead phone.

## 7. Stolen-token protection

Possession alone is insufficient. Require a secure-element challenge response, per-transaction terminal nonce, short token validity, transaction amount/currency binding, server-side status and risk checks, and low emergency limits. Prefer a token PIN or biometric unlock for higher limits. Never put a reusable bank credential on the token.

The owner can revoke the token from another authenticated device or through a recovery/support process. Maintain velocity limits per UPID, authenticator, merchant, and token. Offline tokens are pre-authorized envelopes with a bounded value and expiry, not an offline wallet with unlimited spending. A stolen token can still create risk within its explicitly configured low limit, so production users need provider-grade monitoring and rapid revocation.

## 8. Cryptographic and security architecture

- TLS 1.3 for service and terminal communication; use mTLS or signed terminal credentials for trusted merchant terminals.
- Ed25519 or platform-supported WebAuthn algorithms for authenticator signatures; use a KMS/HSM for server signing keys.
- Encrypt sensitive data in transit and at rest. Store provider access/refresh tokens encrypted with envelope encryption; store only provider tokens, never UPI PINs, CVVs, full PANs, or bank passwords.
- Sign a canonical payment payload containing intent ID, UPID, authenticator ID, provider account ID, amount in minor units, currency, merchant, purpose, nonce, and expiry.
- Reject duplicate intent IDs/nonces, wrong audience, expired timestamps, altered amounts, and cross-provider replay. Use idempotency keys on every create-payment operation.
- Bind device keys to authenticator records and provider tokens to payment-account records. Record key rotation and revocation events.
- Recovery uses multiple independent factors, recovery codes stored as hashes, rate limits, cooling-off periods, notifications, and manual review for risky recovery. Recovery must not silently replace all authenticators.
- Maintain append-only security and transaction audit events with actor, action, request ID, result, and timestamp; protect operational access with least privilege.

## 9. Payment-account linking

`PaymentAccount` is a logical UPID-owned link to a provider. It stores provider name, account type, provider customer/reference ID, capability, status, and consent timestamps. It does not store raw credentials.

Linking is an explicit authorization flow: create link session, redirect/launch provider consent, receive a signed or server-to-server callback, validate state/PKCE and provider identity, store tokenized references, and run a small verification where applicable. Users can set priority and allowed transaction types. Account states are `pending`, `active`, `reauthorization_required`, `suspended`, and `closed`.

Provider-neutral types include `upi`, `bank_account`, `card`, `wallet`, and future `international_account`. Provider adapters translate country-specific identifiers, currencies, mandates, 3-D Secure, consent, settlement, and error codes into a common contract. A PCI-compliant tokenization provider should handle cards in production.

## 10. Payment Orchestrator and adapters

The orchestrator owns payment intent state, idempotency, authorization, risk calls, routing, retries, and reconciliation. It does not contain provider-specific HTTP or credential formats.

```text
PaymentOrchestrator
  -> Policy/Authorization Service
  -> RiskEngine interface
  -> AccountRouter
  -> ProviderRegistry -> ProviderAdapter (UPI, bank, card, wallet, international)
  -> Webhook/Status Normalizer
```

Every adapter implements: capabilities, create authorization, capture/execute, get status, cancel/refund, link account, refresh consent, verify webhook, and normalize provider errors. Adapters must be idempotent and receive a correlation ID. The registry selects by provider, country, currency, account capability, and policy, not by hard-coded `if` chains.

## 11. Transaction lifecycle

`created -> awaiting_authentication -> authorized -> risk_approved -> submitted -> provider_pending -> completed`.

Alternative terminal states are `declined`, `failed`, `cancelled`, `expired`, `refunded`, and `disputed`.

1. Client creates an intent with amount, currency, merchant, and idempotency key.
2. Server validates identity, account capability, limits, and request uniqueness.
3. Server returns a challenge payload.
4. Authenticator signs; server verifies it and calls risk.
5. Orchestrator selects an account and submits through an adapter.
6. Provider response or verified webhook advances the state; duplicate callbacks are harmless.
7. Ledger/audit events and a user receipt are written for every transition.
8. Reconciliation compares provider reports with internal intents and opens exceptions instead of guessing.

## 12. Fraud/risk interface

```text
RiskDecision evaluate(RiskContext) ->
  { decision: allow | step_up | review | deny,
    score, reasons[], limits, policy_version, expires_at }
```

`RiskContext` includes UPID, authenticator, token age, amount/currency, merchant, account/provider, device/terminal, IP/network where appropriate, velocity aggregates, prior outcomes, and offline flag. The interface is synchronous for authorization and asynchronous for monitoring. Reasons are auditable but must not expose sensitive detection rules to clients.

## 13. Offline/emergency payments

Offline support is optional and restricted to enrolled tokens and approved terminals. Before going offline, the service provisions signed envelopes with token ID, maximum amount, currency, merchant scope if needed, expiry, counter/nonce range, and policy version. The secure token enforces one-time counters; the terminal stores the signed record in tamper-resistant storage.

Set conservative per-transaction, daily, and total outstanding limits. No offline account linking, refunds, high-value transfers, international transactions, or policy changes. On reconnection, the terminal uploads records; the server verifies signatures, counters, expiry, and available budget, then submits or rejects them. Reconciliation handles duplicate capture, partial failure, and disputes. Offline acceptance always carries bounded merchant and issuer risk.

## 14. PostgreSQL schema

All tables use UUID primary keys, UTC `timestamptz`, integer minor units for money, and explicit status/check constraints. Add `created_at`, `updated_at`, and an immutable audit strategy where shown.

```text
users
  id UUID PK
  name TEXT NULL
  email TEXT NULL UNIQUE
  status TEXT NOT NULL
  created_at, updated_at TIMESTAMPTZ

payment_identities
  id UUID PK
  upid TEXT NOT NULL UNIQUE
  user_id UUID NOT NULL FK users(id)
  status TEXT NOT NULL
  version INT NOT NULL DEFAULT 1
  created_at, updated_at TIMESTAMPTZ

authenticators
  id UUID PK
  identity_id UUID NOT NULL FK payment_identities(id)
  type TEXT NOT NULL
  label TEXT NOT NULL
  public_key BYTEA NOT NULL
  key_algorithm TEXT NOT NULL
  key_fingerprint TEXT NOT NULL UNIQUE
  status TEXT NOT NULL
  last_used_at TIMESTAMPTZ NULL
  created_at, revoked_at TIMESTAMPTZ NULL

recovery_methods
  id UUID PK
  identity_id UUID NOT NULL FK payment_identities(id)
  type TEXT NOT NULL
  verifier_hash TEXT NULL
  metadata JSONB NOT NULL DEFAULT '{}'
  status TEXT NOT NULL
  created_at, revoked_at TIMESTAMPTZ NULL

providers
  id UUID PK
  code TEXT NOT NULL UNIQUE
  country_code TEXT NULL
  capabilities JSONB NOT NULL
  status TEXT NOT NULL

payment_accounts
  id UUID PK
  identity_id UUID NOT NULL FK payment_identities(id)
  provider_id UUID NOT NULL FK providers(id)
  account_type TEXT NOT NULL
  provider_customer_ref TEXT NULL
  provider_account_ref TEXT NOT NULL
  display_name TEXT NULL
  credential_ref TEXT NULL
  status TEXT NOT NULL
  priority INT NOT NULL DEFAULT 0
  consented_at TIMESTAMPTZ NULL
  UNIQUE(provider_id, provider_account_ref)

payment_intents
  id UUID PK
  identity_id UUID NOT NULL FK payment_identities(id)
  payment_account_id UUID NULL FK payment_accounts(id)
  merchant_ref TEXT NOT NULL
  amount_minor BIGINT NOT NULL
  currency CHAR(3) NOT NULL
  status TEXT NOT NULL
  idempotency_key TEXT NOT NULL
  expires_at TIMESTAMPTZ NOT NULL
  created_at, updated_at TIMESTAMPTZ
  UNIQUE(identity_id, idempotency_key)

payment_authorizations
  id UUID PK
  intent_id UUID NOT NULL UNIQUE FK payment_intents(id)
  authenticator_id UUID NOT NULL FK authenticators(id)
  challenge_hash TEXT NOT NULL UNIQUE
  signature BYTEA NOT NULL
  signed_payload_hash TEXT NOT NULL
  verified_at TIMESTAMPTZ NULL

provider_transactions
  id UUID PK
  intent_id UUID NOT NULL FK payment_intents(id)
  provider_id UUID NOT NULL FK providers(id)
  provider_transaction_ref TEXT NULL
  status TEXT NOT NULL
  request_hash TEXT NOT NULL
  response JSONB NULL
  UNIQUE(provider_id, provider_transaction_ref)

risk_assessments
  id UUID PK
  intent_id UUID NOT NULL FK payment_intents(id)
  decision TEXT NOT NULL
  score NUMERIC NULL
  reasons JSONB NOT NULL
  policy_version TEXT NOT NULL
  created_at TIMESTAMPTZ

idempotency_records
  id UUID PK
  scope TEXT NOT NULL
  key TEXT NOT NULL
  request_hash TEXT NOT NULL
  response JSONB NULL
  created_at TIMESTAMPTZ
  UNIQUE(scope, key)

audit_events
  id UUID PK
  identity_id UUID NULL FK payment_identities(id)
  actor_type TEXT NOT NULL
  actor_ref TEXT NULL
  event_type TEXT NOT NULL
  request_id TEXT NULL
  payload JSONB NOT NULL
  created_at TIMESTAMPTZ
```

For production, add provider webhook events, settlements, refunds/disputes, offline envelopes, consent records, and an append-only double-entry ledger. Do not use the prototype's `account_reference` field for secrets.

## 15. MVP REST API

Use `/api/v1` and OAuth2/JWT or a prototype session layer. Require an idempotency header on payment creation.

```text
POST   /identities                         create a prototype UPID
GET    /identities/{upid}                  get non-sensitive identity summary
POST   /identities/{upid}/authenticators   enroll a simulated authenticator
GET    /identities/{upid}/authenticators   list/revocation status
DELETE /identities/{upid}/authenticators/{id} revoke authenticator
POST   /identities/{upid}/accounts/link    create a simulated/provider link session
GET    /identities/{upid}/accounts         list masked linked accounts
DELETE /identities/{upid}/accounts/{id}     unlink an account
POST   /payment-intents                    create intent and challenge
POST   /payment-intents/{id}/authorize     submit signed authenticator proof
GET    /payment-intents/{id}               get lifecycle status
POST   /payment-intents/{id}/cancel       cancel before submission
POST   /webhooks/{provider}               receive verified provider event
GET    /identities/{upid}/audit            owner-visible audit history
```

The prototype may use a fake adapter and simulated signatures, but the API shapes should already carry provider, currency, idempotency, challenge, and status fields.

## 16. Recommended technology stack

For the current project: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL, psycopg, pytest, httpx, Ruff, mypy or Pyright, and Docker Compose for local PostgreSQL. Use `cryptography`/WebAuthn-compatible libraries for proof experiments. Use Redis only when a real cache, rate limiter, or nonce store is needed.

Production adds a managed KMS/HSM, secrets manager, PCI-compliant card tokenization provider, provider SDKs, durable job/event infrastructure, observability, WAF/API gateway, and a separately reviewed mobile/token client. Do not implement cryptography, card vaulting, or regulated payment rails from scratch.

## 17. MVP versus production

MVP: local PostgreSQL, one fake provider adapter, simulated UPI/bank/card/wallet accounts with masked references, generated test identities, one software authenticator, signed test challenges, synchronous risk rules, payment-intent state machine, idempotency, audit events, and a fake webhook.

Production: regulated PSP/bank/UPI/card integrations, real KYC/AML and sanctions obligations, PCI scope reduction, hardware-backed keys, WebAuthn/mobile secure storage, secure NFC/wearable provisioning, HSM/KMS, production fraud models, ledger/reconciliation, dispute handling, regional data controls, incident response, and independent security/compliance review.

## 18. Safe simulation boundary

Safe to simulate: identity generation, authenticator enrollment with test key pairs, challenge signatures, token theft scenarios, provider adapters, provider responses, webhooks, risk decisions, offline envelopes, limits, state transitions, and reconciliation using fake money.

Requires regulated providers and legal/compliance work: moving real funds, UPI access, bank account connectivity, card PAN handling, wallet custody, KYC/AML, sanctions screening, biometric identity claims, production NFC issuance, and final settlement. Never test with real credentials in this repository.

## 19. Architecture diagram

```text
 [Phone/passkey]   [NFC token]   [Wearable]   [Future biometric]
       \              |              |              /
        +------ Authenticator Proof / Challenge ------+
                           |
                    [API Gateway]
                           |
              [UPID Identity & Auth Service]
                 |       |          |
             [Recovery] [Risk] [Audit/Events]
                           |
                 [Payment Orchestrator]
                    |       |       |
              [Account Router] [Idempotency]
                           |
                    [Provider Registry]
             /             |              \
       [UPI adapter] [Bank adapter] [Card adapter]
             \             |              /
              [Wallet / International adapters]
                           |
                  [External regulated providers]

 [PostgreSQL: identities, keys, accounts, intents, risk, audit]
 [KMS/HSM: server keys] [Secrets vault: encrypted provider tokens]
 [Webhook ingress] -> [Normalizer] -> [Orchestrator state machine]
```

## 20. Exact implementation order

1. Establish the domain vocabulary, PostgreSQL configuration, Alembic migrations, UUID/timestamp conventions, and status enums. Keep existing endpoints working only as a compatibility layer; do not add real credentials.
2. Replace the three-table prototype model with identity, authenticator, provider, and payment-account entities and migration tests.
3. Add a repository/service boundary so FastAPI routes do not own transaction logic.
4. Add UPID creation, lookup, lifecycle, and masked account APIs.
5. Add simulated authenticator enrollment, challenge creation, signature verification, revocation, and audit events.
6. Add provider interfaces, registry, and one fake adapter.
7. Add payment intents, canonical payloads, idempotency, and the lifecycle state machine.
8. Add the deterministic MVP risk interface and limits.
9. Add fake webhooks, reconciliation, refunds-as-simulation, and failure tests.
10. Add offline envelope simulation and stolen-token/replay test cases.
11. Add contract tests for a second provider adapter and international currency/country fields.
12. Only after the domain and tests are stable, evaluate real provider sandboxes, mobile secure storage, hardware tokens, compliance, and production operations.

### Local startup initialization

The local startup path creates all model tables before running compatibility migrations. This ensures the first initialization can create the partial unique index `idx_transactions_idempotency_key`; repeated initialization remains safe because the migrations use existence checks.

The compatibility wrapper `evaluate_risk_for_transaction()` preserves its two-value return contract, `(allowed, reasons)`, and forwards the actual reasons returned by `evaluate_security_decision()`.

## Step 1 only: immediate implementation task

Do only this next:

1. Add PostgreSQL settings driven by environment variables, while preserving SQLite as an explicit local fallback if needed.
2. Add Alembic and create the initial migration baseline; do not use `Base.metadata.create_all` as the production schema mechanism.
3. Add shared SQLAlchemy conventions for UUID primary keys, UTC timestamps, and a small set of validated status values.
4. Add a database health check and a migration test that creates a clean database and upgrades it successfully.
5. Document the local setup and required environment variables.

Acceptance criteria for Step 1: a clean PostgreSQL database can be upgraded from zero migrations, the FastAPI app starts without creating tables implicitly, the existing prototype data is not silently destroyed, and no raw bank/card credentials are introduced.

## Step 3: Payment Authorization and Routing Prototype

Step 3 adds a simulated payment-request layer while preserving the existing identity, authentication-method, and payment-account APIs. A payment request records the identity, selected linked payment account, selected enrolled authentication method, amount, currency, recipient reference, description, lifecycle status, and timestamps.

The prototype lifecycle is:

`pending -> simulated_success`

An expired request becomes `expired`, and a request that is already authorized cannot be authorized again. Creation and authorization verify that the selected payment account and authentication method belong to the requested Universal Payment Identity. Authorization also requires the authentication method to remain active.

Payment routing only identifies the linked account and provider that would be used. It does not call a bank, UPI network, card processor, wallet, or payment gateway, and it never transfers real money. The authorization response explicitly reports `simulation: true` and `real_money_transferred: false`.

The authentication method is treated as an enrolled credential reference only. Step 3 does not verify possession of a phone, NFC token, wearable, PIN, or biometric and does not claim that any method was genuinely authenticated. Real challenge signing, provider integration, risk decisions, idempotency, and settlement belong to later stages.

### Step 3 API

```text
POST /identity/{upi_id}/payment-requests
GET  /identity/{upi_id}/payment-requests
POST /identity/{upi_id}/payment-requests/{payment_request_id}/authorize
```

Payment request creation requires a positive amount, three-letter currency, recipient reference, linked payment-account ID, and active authentication-method ID. The optional expiry defaults to fifteen minutes.

## Phase 4A: Device-Independent Offline Payment Prototype

Phase 4A adds an identity-owned alternative-device registry for simulated dead-phone flows. Devices can be registered, listed, and revoked without deleting their records. Supported prototype device types are `nfc`, `wearable`, and `security_key`.

Offline payment requests contain an amount, `INR` currency, recipient reference, optional description, alternative device ID, expiration, and a unique transaction nonce. An active device belonging to the identity is required. The prototype enforces a maximum offline transaction amount of INR 1,000 and records accepted requests as `simulated_success`; it never contacts a payment network or transfers money. Reusing a nonce returns a conflict to prevent replay.

### Phase 4A API

```text
POST   /identity/{upi_id}/devices
GET    /identity/{upi_id}/devices
DELETE /identity/{upi_id}/devices/{device_id}
POST   /identity/{upi_id}/offline-payment-requests
GET    /identity/{upi_id}/offline-payment-requests/{payment_request_id}
```

The offline flow is not real NFC, wearable, biometric, or cryptographic authentication. A device record represents enrollment only; possession and ownership are not verified in this prototype. The response explicitly reports `simulation: true` and `real_money_transferred: false`.

## Phase 8: Security and Risk Engine Prototype

Phase 8 adds a lightweight prototype security gate to the existing payment flow. The engine validates identity and account lifecycle status, authentication method activity, device activity, amount and currency sanity checks, request expiry, nonce replay protection, and a simple recipient velocity/risk heuristic. The decision is reported as `ALLOW`, `REVIEW`, or `DENY`, and each denied or reviewed request includes a clear reason string without exposing secrets or credentials.

The prototype is intentionally local and simulation-only. It does not implement real biometrics, cryptographic challenge validation, KYC/AML screening, or provider-grade fraud detection. It preserves the existing SQLite prototype and only applies safe risk checks at the payment-request, route-payment, and offline-payment boundaries.

The security layer is designed to protect the current prototype without altering the approved architecture:

- identity must be active before a payment route is allowed
- payment accounts and authentication methods must remain active
- revoked devices are rejected for offline flows
- expired payment requests are rejected
- duplicate nonces/idempotency keys remain blocked
- abnormal high-value or receiver velocity conditions trigger a review or deny decision
- simulated routing and ledger flows continue to operate without real bank or external payment provider integration