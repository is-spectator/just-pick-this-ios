# Email Auth Implementation Report

Date: 2026-06-15

## Scope

Implemented email verification-code login for the Pipi backend and iOS app. Password login, phone login, OAuth, and product Agent logic changes were intentionally excluded.

## Backend Changes

- Added email auth configuration in `app.config.Settings`:
  - `JWT_SECRET`
  - `ACCESS_TOKEN_TTL_SECONDS`
  - `REFRESH_TOKEN_TTL_DAYS`
  - `EMAIL_PROVIDER=console|smtp`
  - `EMAIL_FROM_NAME`
  - `EMAIL_FROM_ADDRESS`
  - `SMTP_HOST`
  - `SMTP_PORT`
  - `SMTP_USERNAME`
  - `SMTP_PASSWORD`
  - `SMTP_USE_SSL`
  - `SMTP_USE_STARTTLS`
  - `SMTP_TIMEOUT_SECONDS`
- Production/staging guardrails now require `JWT_SECRET` and SMTP config, and reject `EMAIL_PROVIDER=console`.
- Added DB migration `0012_email_auth`:
  - `users.email`
  - `users.email_verified_at`
  - `users.auth_provider`
  - `users.last_login_at`
  - `users.status`
  - `email_login_codes`
  - `auth_sessions`
  - `auth_audit_logs`
  - `user_devices`
- Added SMTP/console email sender. Console sender is dev/test only.
- Added auth services:
  - 6-digit email code generation.
  - Code hash storage only; plaintext code is never stored.
  - Request cooldown and hourly rate limits.
  - HS256 access tokens without adding a new JWT dependency.
  - Refresh-token rotation with hash-only storage.
  - Logout revocation.
- Added `/v1/auth/*` routes:
  - `POST /v1/auth/request-code`
  - `POST /v1/auth/verify-code`
  - `POST /v1/auth/refresh`
  - `POST /v1/auth/logout`
  - `GET /v1/auth/me`
- `/v1/chat/turn` now accepts `Authorization: Bearer <access_token>` and resolves the email account before falling back to device identity.
- Device anonymous data is merged into the email user on successful verification. Merged tables include conversations, turns, questions, recommendation cards, help cards, help answers, light events, reward events, and auth audit logs.

## iOS Changes

- Added Keychain-backed storage for:
  - device uid, with migration from the old `UserDefaults` value
  - access token
  - refresh token
  - signed-in email
- Added `AuthAPIService` for email code request, verify, refresh, and logout.
- Added `EmailLoginView` sheet.
- The `皮皮 >` title is now the account entry point.
- Backend requests automatically attach `Authorization: Bearer` when an access token exists.
- Backend requests silently refresh once on HTTP 401, then retry the original request.

## Security Notes

- SMTP password is a `SecretStr` and is masked in SMTP error messages.
- Email codes are stored as HMAC hashes.
- Refresh tokens are stored as SHA-256 hashes.
- Access tokens are short-lived and signed with `JWT_SECRET`.
- Dev/test may use `EMAIL_PROVIDER=console`; production/staging cannot.

## Verification

Commands run:

```sh
cd backend
uv run alembic upgrade head
uv run pytest app/tests/test_email_auth_api.py -q -rx
uv run pytest app/tests/test_production_config_guard.py -q -rx
uv run pytest app/tests/test_email_auth_api.py app/tests/test_production_config_guard.py app/tests/test_pipi_runtime_acceptance.py app/tests/test_eval_smoke_bypass_guardrails.py -q -rx
uv run --extra dev pytest app/tests -q -rx
uv run --extra dev ruff check app tests
uv run alembic heads
uv run alembic current
./scripts/test_security_gate.sh
```

Results:

- Email auth API tests: passed.
- Production config guard tests: passed.
- Chat/runtime/security regression subset: passed.
- Full backend `app/tests`: passed.
- Ruff: passed.
- Alembic head/current: `0012_email_auth`.
- Security gate script: passed.

Swift build:

```sh
xcodebuild -scheme JustPickThisIOS -destination 'id=6EB511A7-378D-4B6C-B027-A9E976F75F81' build
```

Result: `BUILD SUCCEEDED`.

## Deployment Requirements

Remote/prod env must provide:

```sh
JWT_SECRET=...
EMAIL_PROVIDER=smtp
EMAIL_FROM_NAME=皮皮
EMAIL_FROM_ADDRESS=...
SMTP_HOST=...
SMTP_PORT=465
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_USE_SSL=true
SMTP_USE_STARTTLS=false
```

Run migration before serving new auth routes:

```sh
cd backend
uv run alembic upgrade head
```

## Remaining Notes

- This implementation does not add password auth by design.
- This implementation does not change Pipi Agent routing, reasoner, retrieval, card creation, or help-card finalization logic except user resolution.
- The iOS account entry is intentionally minimal and attached to the existing `皮皮 >` affordance.
