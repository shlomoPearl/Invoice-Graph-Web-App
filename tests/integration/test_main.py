import base64
import contextlib
import json
import os
import sys
from unittest.mock import MagicMock
import itsdangerous
import pytest
from fastapi.testclient import TestClient

# --- Import main.py against a fake-but-syntactically-valid Postgres URL ---
os.environ["DB_URL"] = "postgresql+psycopg2://fake:fake@localhost:5432/fake"
os.environ["KEY"] = "test-secret-key-for-sessions"
os.environ["REDIRECT_URI"] = "http://testserver/oauth2callback"
# Force re-import of main.py to pick up the new DB_URL and avoid caching from previous tests
for _mod in ("main", "db", "model", "storage"):
    sys.modules.pop(_mod, None)

import main


@contextlib.asynccontextmanager
async def _noop_lifespan(app):
    yield
main.app.router.lifespan_context = _noop_lifespan

def _fake_get_db():
    yield MagicMock()
main.app.dependency_overrides[main.get_db] = _fake_get_db

SESSION_COOKIE_NAME = "session_id"
TEST_COOKIE_DOMAIN = "testserver.local"  # matches TestClient's default host
_signer = itsdangerous.TimestampSigner(os.environ["KEY"])

def make_session_cookie(session_dict: dict) -> str:
    data = base64.b64encode(json.dumps(session_dict).encode("utf-8"))
    signed = _signer.sign(data)
    return signed.decode("utf-8")

def set_session_cookie(client: TestClient, session_dict: dict) -> None:
    client.cookies.set(SESSION_COOKIE_NAME, make_session_cookie(session_dict), domain=TEST_COOKIE_DOMAIN)

def read_session_cookie(client: TestClient) -> dict:
    raw = client.cookies.get(SESSION_COOKIE_NAME, domain=TEST_COOKIE_DOMAIN)
    if not raw:
        return {}
    data = _signer.unsign(raw.encode("utf-8"))
    return json.loads(base64.b64decode(data))

@pytest.fixture
def client():
    with TestClient(main.app, follow_redirects=False) as client:
        yield client

@pytest.fixture
def logged_in_client(client):
    set_session_cookie(client, {"session_id": "fake-db-session-id"})
    return client


class TestIndexGet:
    def test_renders_index_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Bill Parser" in response.text


class TestLoginPost:
    def test_empty_required_field_returns_400(self, client):
        response = client.post("/", data={
            "email": "",
            "currency": "$",
            "start_date": "01/03/2024",
            "end_date": "15/03/2024",
        })
        assert response.status_code == 400
        assert "Missing required form fields" in response.text

    def test_missing_required_field_returns_422(self, client):
        # built-in FastAPI validation will return 422 for missing required fields
        response = client.post("/", data={
            "currency": "$",
            "start_date": "01/03/2024",
            "end_date": "15/03/2024",
        })
        assert response.status_code == 422

    def test_no_session_redirects_to_login_and_stashes_form_data(self, monkeypatch, client):
        monkeypatch.setattr(main, "validate_session", lambda db, sid: None)
        response = client.post("/", data={
            "email": "billing@company.com",
            "currency": "$",
            "start_date": "01/03/2024",
            "end_date": "15/03/2024",
        })
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login"
        session = read_session_cookie(client)
        assert session["form_data"]["email"] == "billing@company.com"

    def test_valid_session_and_token_processes_flow_and_returns_graph(self, monkeypatch, logged_in_client):
        monkeypatch.setattr(main, "validate_session", lambda db, sid: "user-123")
        monkeypatch.setattr(main, "load_user_token", lambda db, gid: {"token": "abc"})
        monkeypatch.setattr(main.GmailAuth, "get_service_from_token_dict", staticmethod(lambda td: MagicMock()))

        mock_gmail_instance = MagicMock()
        mock_gmail_instance.search_mail.return_value = {"03/2024": ["<html>fake</html>"]}
        monkeypatch.setattr(main, "Gmail", MagicMock(return_value=mock_gmail_instance))

        mock_bill_reader = MagicMock()
        mock_bill_reader.parser.return_value = {"03/2024": 150.0}
        monkeypatch.setattr(main, "ReadBill", MagicMock(return_value=mock_bill_reader))

        mock_graph = MagicMock()
        mock_graph.get_html_graph.return_value = "<div>fake graph</div>"
        monkeypatch.setattr(main, "GraphPlot", MagicMock(return_value=mock_graph))

        response = logged_in_client.post("/", data={
            "email": "billing@company.com",
            "currency": "$",
            "start_date": "01/03/2024",
            "end_date": "15/03/2024",
        })
        assert response.status_code == 200
        assert "fake graph" in response.text

    def test_expired_token_redirects_to_login_instead_of_processing(self, monkeypatch, logged_in_client):
        monkeypatch.setattr(main, "validate_session", lambda db, sid: "user-123")
        monkeypatch.setattr(main, "load_user_token", lambda db, gid: None)  # expired/inactive

        response = logged_in_client.post("/", data={
            "email": "billing@company.com",
            "currency": "$",
            "start_date": "01/03/2024",
            "end_date": "15/03/2024",
        })
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login"

    def test_processing_error_returns_500(self, monkeypatch, logged_in_client):
        monkeypatch.setattr(main, "validate_session", lambda db, sid: "user-123")
        monkeypatch.setattr(main, "load_user_token", lambda db, gid: {"token": "abc"})
        monkeypatch.setattr(main.GmailAuth, "get_service_from_token_dict", staticmethod(lambda td: MagicMock()))
        broken_gmail = MagicMock()
        broken_gmail.search_mail.side_effect = RuntimeError("Gmail API failure")
        monkeypatch.setattr(main, "Gmail", MagicMock(return_value=broken_gmail))
        response = logged_in_client.post("/", data={
            "email": "billing@company.com",
            "currency": "$",
            "start_date": "01/03/2024",
            "end_date": "15/03/2024",
        })
        assert response.status_code == 500
        assert "Processing error" in response.text

    def test_redirects_to_google_auth_url_and_stores_state(self, monkeypatch, client):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/fake-auth", "csrf-state-xyz")
        monkeypatch.setattr(main.GmailAuth, "create_flow", lambda self: mock_flow)
        response = client.get("/auth/login")
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "https://accounts.google.com/fake-auth"
        session = read_session_cookie(client)
        assert session["oauth_state"] == "csrf-state-xyz"


class TestOAuthCallback:
    def test_missing_saved_state_returns_400(self, client):
        response = client.get("/oauth2callback", params={"code": "abc", "state": "xyz"})
        assert response.status_code == 400
        assert "Invalid OAuth state" in response.text

    def test_mismatched_state_returns_400(self, client):
        set_session_cookie(client, {"oauth_state": "expected-state"})
        response = client.get("/oauth2callback", params={"code": "abc", "oauth_state": "wrong-state"})
        assert response.status_code == 400
        assert "Invalid OAuth state" in response.text

    def test_valid_callback_with_no_pending_form_redirects_home(self, monkeypatch, client):
        set_session_cookie(client, {"oauth_state": "matching-state"})
        monkeypatch.setattr(main.GmailAuth, "exchange_code", lambda self, code: None)
        monkeypatch.setattr(main.GmailAuth, "get_user_db_dict", lambda self: {
            "user_id": "user-123",
            "email": "user@example.com",
            "token_dict": {"token": "abc"},
        })
        monkeypatch.setattr(main, "save_user_token", MagicMock())
        monkeypatch.setattr(main, "create_session", lambda db, uid: "new-db-session-id")
        response = client.get("/oauth2callback", params={"code": "auth-code", "state": "matching-state"})
        session = read_session_cookie(client)
        
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert session["session_id"] == "new-db-session-id"

    def test_valid_callback_with_pending_form_renders_loading_page(self, monkeypatch, client):
        set_session_cookie(client, {
            "oauth_state": "matching-state",
            "form_data": {"email": "billing@company.com", "currency": "$",
                          "start_date": "01/03/2024", "end_date": "15/03/2024"},
        })
        monkeypatch.setattr(main.GmailAuth, "exchange_code", lambda self, code: None)
        monkeypatch.setattr(main.GmailAuth, "get_user_db_dict", lambda self: {
            "user_id": "user-123",
            "email": "user@example.com",
            "token_dict": {"token": "abc"},
        })
        monkeypatch.setattr(main, "save_user_token", MagicMock())
        monkeypatch.setattr(main, "create_session", lambda db, uid: "new-db-session-id")
        response = client.get("/oauth2callback", params={"code": "auth-code", "state": "matching-state"})
        session = read_session_cookie(client)

        assert response.status_code == 200
        assert "Preparing your graph" in response.text
        assert "pending_form_data" in session
        assert "form_data" not in session  # popped, not just copied

    def test_exchange_code_failure_returns_500_with_oauth_error_prefix(self, monkeypatch, client):
        set_session_cookie(client, {"oauth_state": "matching-state"})
        def raise_error(self, code):
            raise RuntimeError("invalid_grant")
        monkeypatch.setattr(main.GmailAuth, "exchange_code", raise_error)
        response = client.get("/oauth2callback", params={"code": "bad-code", "state": "matching-state"})
        
        assert response.status_code == 500
        assert "OAuth Error" in response.text


class TestProcessAfterOAuth:
    def test_no_session_redirects_to_login(self, monkeypatch, client):
        monkeypatch.setattr(main, "validate_session", lambda db, sid: None)
        response = client.get("/process_after_oauth")
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login"

    def test_no_pending_form_data_redirects_home(self, monkeypatch, logged_in_client):
        monkeypatch.setattr(main, "validate_session", lambda db, sid: "user-123")
        monkeypatch.setattr(main, "load_user_token", lambda db, gid: {"token": "abc"})
        monkeypatch.setattr(main.GmailAuth, "get_service_from_token_dict", lambda td: MagicMock())
        response = logged_in_client.get("/process_after_oauth")
        assert response.status_code == 303
        assert response.headers["location"] == "/"

    def test_pending_form_data_triggers_processing(self, monkeypatch, client):
        set_session_cookie(client, {
            "session_id": "fake-db-session-id",
            "pending_form_data": {"email": "billing@company.com", "currency": "$",
                                   "start_date": "01/03/2024", "end_date": "15/03/2024"},
        })
        monkeypatch.setattr(main, "validate_session", lambda db, sid: "user-123")
        monkeypatch.setattr(main, "load_user_token", lambda db, gid: {"token": "abc"})
        monkeypatch.setattr(main.GmailAuth, "get_service_from_token_dict", lambda td: MagicMock())
        mock_gmail_instance = MagicMock()
        mock_gmail_instance.search_mail.return_value = {"03/2024": ["<html>test</html>"]}
        monkeypatch.setattr(main, "Gmail", MagicMock(return_value=mock_gmail_instance))
        mock_bill_reader = MagicMock()
        mock_bill_reader.parser.return_value = {"03/2024": 75.0}
        monkeypatch.setattr(main, "ReadBill", MagicMock(return_value=mock_bill_reader))
        mock_graph = MagicMock()
        mock_graph.get_html_graph.return_value = "<div>test graph</div>"
        monkeypatch.setattr(main, "GraphPlot", MagicMock(return_value=mock_graph))
        response = client.get("/process_after_oauth")

        assert response.status_code == 200
        assert "test graph" in response.text


class TestDownloadGraph:
    def test_no_bill_dict_in_session_returns_400(self, client):
        response = client.get("/download", params={"format": "png"})
        assert response.status_code == 400
        assert "No bill data found in session" in response.text

    def test_png_download_returns_correct_content_type(self, monkeypatch, client):
        set_session_cookie(client, {"bill_dict": {"03/2024": 100.0}})
        mock_graph = MagicMock()
        mock_graph.download_by_f.return_value = b"\x89PNG\r\n\x1a\ntestpngbytes"
        monkeypatch.setattr(main, "GraphPlot", MagicMock(return_value=mock_graph))

        response = client.get("/download", params={"format": "png"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert "attachment; filename=graph.png" in response.headers["content-disposition"]

    def test_pdf_download_returns_correct_content_type(self, monkeypatch, client):
        set_session_cookie(client, {"bill_dict": {"03/2024": 100.0}})
        mock_graph = MagicMock()
        mock_graph.download_by_f.return_value = b"%PDF-1.4 testpdfbytes"
        monkeypatch.setattr(main, "GraphPlot", MagicMock(return_value=mock_graph))

        response = client.get("/download", params={"format": "pdf"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    def test_invalid_download_format(self, client):
        set_session_cookie(client, {"bill_dict": {"03/2024": 100.0}})
        with pytest.raises(ValueError, match="Invalid format. Supported formats are: 'png', 'pdf'."):
            client.get("/download", params={"format": "bmp"})