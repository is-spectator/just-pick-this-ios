# Real Email Verification Config Report

Date: 2026-06-16

## Summary

The backend email verification flow is now configured to use a real SMTP provider instead of the local console-only provider.

Reference configuration was taken from:

`/Users/fangnaoke/Documents/ai_work/worldcup_odds_tracker/.env`

Secrets were copied into local and remote environment files without printing them to terminal output or committing them to source files.

## Local Changes

- Updated `backend/.env` with real email verification settings:
  - `EMAIL_PROVIDER=smtp`
  - Alibaba Cloud Enterprise Email SMTP host/port and SSL mode
  - sender name/address
  - SMTP username/password
  - JWT secret and token TTL defaults
- Updated `backend/.env.example` with the required email auth variables and Alibaba Cloud SMTP example settings.
- Updated `backend/app/tests/test_email_auth_api.py` so auth unit tests explicitly force `EMAIL_PROVIDER=console`.
  - Product/dev local runtime can use real SMTP.
  - Tests remain deterministic and do not send real emails.

## Remote Deployment

Target backend:

`http://67.230.169.161:8788`

Remote backend path:

`/opt/just-pick-this/backend`

Actions:

- Created a remote backup before deployment:
  - `/opt/just-pick-this/backend-backup-email-20260616T011957Z`
- Synced current backend application code and Alembic migrations.
- Merged only email/JWT environment keys into the remote `.env`.
- Preserved the remote `.env` and other unrelated runtime configuration.
- Ran:
  - `uv sync --no-dev`
  - `uv run alembic upgrade head`
  - `uv run alembic current`
- Restarted:
  - `just-pick-this-backend.service`

## Verification

Local tests:

```bash
cd backend
uv run pytest app/tests/test_email_auth_api.py app/tests/test_production_config_guard.py -q -rx
```

Result:

`18 passed`

Remote checks:

- `GET /health` returned `200`.
- Remote settings load confirmed:
  - `EMAIL_PROVIDER=smtp`
  - SMTP host/user/password present
  - JWT secret present
- Remote SMTP login smoke passed.
- Remote Alembic head is `0012_email_auth`.

## Notes

- No arbitrary verification email was sent during this setup.
- Full end-to-end verification can now be tested from the app by entering an email address and requesting a code.
- The response will not include `dev_code` in production SMTP mode.
