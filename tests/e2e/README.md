# End-to-End Tests

Real browser (Playwright/Chromium) driving the actual Invoice-Graph stack via
`docker-compose` -- real FastAPI, real Postgres, real Jinja2 templates, real
session cookies. The only thing stubbed is Google itself (OAuth + Gmail API),
via a small local FastAPI stub (`google_stub_app.py`) — see the top of that
file and `conftest.py` for why (server-to-Google calls happen in the
*backend*, not the browser, so Playwright's own request interception can't
reach them).

## One-time setup

```bash
pip install -r tests/e2e/requirements-e2e.txt
playwright install chromium
```

You'll also need your normal project `.env` at the repo root (same one
`docker-compose.yml` already uses via `env_file: .env`) — this suite reads
`DB_USER`/`DB_PASSWORD`/`DB_NAME`/`KEY`/`ENC_KEY` from it directly to seed
data and sign session cookies that match what the running app expects.

## Running

```bash
# 1. Start the full stack + Google stub
docker compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yml up -d

# 2. Run the E2E suite (pytest.ini excludes tests/e2e from the default
#    `pytest` run since it needs Docker+Playwright — reset addopts to
#    include it explicitly)
pytest tests/e2e/ -o addopts="" -v

# 3. Tear down
docker compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yml down
```

If the stack isn't up, tests fail immediately with a clear message
(`verify_stack_is_up` in `conftest.py`) instead of hanging or timing out
mysteriously.

## What's covered

- **`TestFreshLoginFlow`** — cold start, zero prior session: submit the
  form → redirected through `/auth/login` → the stubbed Google consent
  screen (auto-approves, no real Google account needed) → `/oauth2callback`
  → loading page → graph renders with the seeded invoice data. Exercises the
  full OAuth handshake end-to-end.
- **`TestReturningUserFlow`** — a user with a valid, already-stored token
  (pre-seeded directly into Postgres via the real `storage.py` functions, so
  it's encrypted exactly as production would) goes straight from form
  submission to the graph, with no OAuth redirect at all.
- **`TestDownloadButtons`** — the PNG/PDF download links on the graph page
  actually produce downloadable files with the right filenames.

## How the Google stub works

- `discovery_docs.py` — hand-trimmed Google API discovery documents
  (sourced from the real ones bundled with `google-api-python-client`),
  containing only the 4 methods Invoice-Graph actually calls.
- `google_stub_app.py` — a FastAPI app serving those discovery docs plus
  fake `/o/oauth2/v2/auth` (auto-approves), `/token`, Gmail
  `messages.list`/`get`/`attachments.get`, and `oauth2/v2/userinfo`
  endpoints. Seedable per-test via `POST /_stub/seed`.
- `credentials.stub.json` — a `credentials.json` whose `auth_uri`/`token_uri`
  point at the stub instead of real Google.
- **`gmail_auth.py` has two small, backward-compatible additions**:
  `GOOGLE_CREDENTIALS_FILE` and `GOOGLE_API_DISCOVERY_URL` env vars, both
  no-ops when unset (production behavior is byte-for-byte unchanged). Only
  `docker-compose.e2e.yml` sets them, pointing the running app at the stub.

This whole mechanism was verified against the **real**
`google-auth-oauthlib`/`googleapiclient` libraries (not mocked) before the
Playwright layer was written on top of it — running the stub locally via
`uvicorn` and driving `GmailAuth`/`Gmail` directly confirmed the OAuth
handshake, discovery-doc-based service building, and Gmail message/
attachment fetching all work correctly against it.

## Known limitation found along the way

Building this surfaced a real bug in `date_op.py`'s `increment_date()`: it
naively does `month += 1` without validating the day exists in the target
month. A date range ending on the 29th-31st of a month (e.g. "the whole
month of March") produces a Gmail `before:` filter like `2024/04/31`, which
isn't a real calendar date. Pinned down as a regression test in
`test_date_op.py::test_month_end_date_produces_invalid_calendar_date_known_bug`.
