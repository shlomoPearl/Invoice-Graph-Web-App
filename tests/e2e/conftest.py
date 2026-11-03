"""
Fixtures for the E2E suite. Assumes the full stack is already running via:

    docker compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yml up -d

This suite talks to that running stack from the OUTSIDE, like a real user
would: HTTP requests to localhost:8000 (the app) via Playwright, direct
Postgres access to localhost:5432 (for pre-seeding a "returning user"
scenario, reusing the real storage.py functions so we're seeding data in
exactly the shape the app itself would produce), and HTTP requests to
localhost:9090 (the Google stub's test-control endpoints) to configure what
"Gmail" returns for each scenario.

Requires: pip install pytest-playwright && playwright install chromium
"""
import base64
import json
import os
import sys
import uuid

import pytest
import requests
from dotenv import load_dotenv

APP_BASE_URL = os.getenv("E2E_APP_URL", "http://localhost:8000")
STUB_BASE_URL = os.getenv("E2E_STUB_URL", "http://localhost:9090")

# Load the SAME .env the docker-compose fastapi service uses (env_file: .env)
# from the project root, so ENC_KEY/DB_* here match what's inside the
# container -- required for our directly-seeded encrypted tokens to decrypt
# correctly when the running app reads them back.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
sys.path.insert(0, _PROJECT_ROOT)


@pytest.fixture(scope="session", autouse=True)
def verify_stack_is_up():
    """Fail fast with a clear message if the E2E stack isn't running, rather
    than letting every test time out individually against a closed port."""
    try:
        requests.get(APP_BASE_URL, timeout=3)
    except requests.exceptions.ConnectionError:
        pytest.exit(
            f"Could not reach {APP_BASE_URL}. Start the E2E stack first:\n"
            f"  docker compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yml up -d",
            returncode=1,
        )
    try:
        requests.get(f"{STUB_BASE_URL}/_stub/health", timeout=3)
    except requests.exceptions.ConnectionError:
        pytest.exit(f"Could not reach the Google stub at {STUB_BASE_URL}.", returncode=1)


@pytest.fixture(autouse=True)
def reset_stub():
    """Every test starts with a clean stub fixture state."""
    requests.post(f"{STUB_BASE_URL}/_stub/reset", timeout=3)
    yield


def seed_stub_gmail_data(messages_list: dict, messages_by_id: dict, attachments_by_id: dict = None):
    payload = {
        "messages_list": messages_list,
        "messages_by_id": messages_by_id,
        "attachments_by_id": attachments_by_id or {},
    }
    requests.post(f"{STUB_BASE_URL}/_stub/seed", json=payload, timeout=3)


def make_html_invoice_message(msg_id: str, date_header: str, html_body: str) -> dict:
    encoded = base64.urlsafe_b64encode(html_body.encode("utf-8")).decode("ascii")
    return {
        "id": msg_id,
        "payload": {
            "headers": [{"name": "Date", "value": date_header}],
            "parts": [{"mimeType": "text/html", "body": {"data": encoded}}],
        },
    }


@pytest.fixture
def seeded_user():
    """
    Pre-seed a fully authenticated user + valid session directly in Postgres,
    reusing the real storage.py functions (same encryption, same schema) so
    the running app treats it exactly like a real logged-in user. Returns
    the raw session_id string, which tests set as the app's session cookie.
    """
    from unittest.mock import MagicMock
    sys.modules.setdefault("transformers", MagicMock())

    # DB_URL here targets localhost (host machine), not the "postgres"
    # hostname used inside the docker network.
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    os.environ["DB_URL"] = f"postgresql+psycopg2://{db_user}:{db_password}@localhost:5432/{db_name}"

    for mod in ("db", "model", "storage"):
        sys.modules.pop(mod, None)
    import importlib
    db = importlib.import_module("db")
    model = importlib.import_module("model")
    storage = importlib.import_module("storage")

    db.Base.metadata.create_all(bind=db.engine)
    session = db.SessionLocal()

    g_id = f"e2e-user-{uuid.uuid4().hex[:8]}"
    storage.save_user_token(session, g_id, "e2e@example.com", {
        "token": "seeded-access-token",
        "refresh_token": "seeded-refresh-token",
        "token_uri": f"{STUB_BASE_URL}/token",
        "client_id": "stub-client-id",
        "client_secret": "stub-client-secret",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    })
    session_id = storage.create_session(session, g_id)
    session.close()

    yield session_id

    # Cleanup
    session = db.SessionLocal()
    session.query(model.SessionToken).filter_by(g_id=g_id).delete()
    session.query(model.User).filter_by(g_id=g_id).delete()
    session.commit()
    session.close()
