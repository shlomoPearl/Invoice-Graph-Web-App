"""
A lightweight, test-only stub for Google's OAuth2 + Gmail API surface.

This is NOT a general-purpose Google mock -- it implements exactly the
endpoints Invoice-Graph's `gmail_auth.py` / `gmail.py` actually call, no
more:

  - GET  /discovery/v1/apis/{api}/{version}/rest   (discovery docs)
  - GET  /o/oauth2/v2/auth                          (authorize -- auto-approves)
  - POST /token                                     (token exchange)
  - GET  /gmail/v1/users/{userId}/profile
  - GET  /gmail/v1/users/{userId}/messages
  - GET  /gmail/v1/users/{userId}/messages/{id}
  - GET  /gmail/v1/users/{userId}/messages/{messageId}/attachments/{id}
  - GET  /oauth2/v2/userinfo

Plus two test-control endpoints for seeding fixture data per scenario:
  - POST  /_stub/seed   {"messages": {...}, "profile": {...}, "userinfo": {...}}
  - POST  /_stub/reset

Run standalone with: uvicorn google_stub_app:app --port 9090
"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse

from discovery_docs import gmail_v1_doc, oauth2_v2_doc

app = FastAPI(title="google-stub")

# Base URL the stub reports itself as, in discovery docs' rootUrl. Must match
# how the FastAPI app under test can actually reach this stub (e.g. the
# docker-compose service name/port, or localhost when run standalone).
STUB_BASE_URL = os.getenv("STUB_BASE_URL", "http://localhost:9090/")

# In-memory fixture store, reset between test scenarios via /_stub/reset.
_fixtures = {
    "profile": {"emailAddress": "invoices@example.com"},
    "userinfo": {"id": "stub-user-123"},
    "messages_list": {"messages": []},   # {"messages": [{"id": "m1"}, ...]}
    "messages_by_id": {},                # {"m1": {...full message payload...}}
    "attachments_by_id": {},             # {"att1": {"data": "<base64url>"}}
}


# ---------------------------------------------------------------------------
# Discovery documents
# ---------------------------------------------------------------------------

@app.get("/discovery/v1/apis/{api}/{version}/rest")
def discovery(api: str, version: str):
    if api == "gmail" and version == "v1":
        return gmail_v1_doc(STUB_BASE_URL)
    if api == "oauth2" and version == "v2":
        return oauth2_v2_doc(STUB_BASE_URL)
    return JSONResponse({"error": f"no stub discovery doc for {api}/{version}"}, status_code=404)


# ---------------------------------------------------------------------------
# OAuth2 authorize + token endpoints
# ---------------------------------------------------------------------------

@app.get("/o/oauth2/v2/auth")
def authorize(request: Request):
    """
    Stands in for Google's consent screen. Real Google would show the user
    a login/consent UI here; the stub skips straight to "approved" and
    redirects back to the app's redirect_uri with a fake auth code -- this
    is the standard approach for E2E-testing OAuth flows without a real IdP.
    """
    params = request.query_params
    redirect_uri = params.get("redirect_uri")
    state = params.get("state", "")
    return RedirectResponse(f"{redirect_uri}?code=stub-auth-code&state={state}", status_code=302)


@app.post("/token")
async def token(request: Request):
    # google-auth-oauthlib posts form-encoded data; we don't need to inspect
    # it, just return a well-formed token response.
    return JSONResponse({
        "access_token": "stub-access-token",
        "refresh_token": "stub-refresh-token",
        "expires_in": 3599,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/gmail.readonly "
                 "https://www.googleapis.com/auth/userinfo.profile",
    })


# ---------------------------------------------------------------------------
# Gmail API
# ---------------------------------------------------------------------------

@app.get("/gmail/v1/users/{user_id}/profile")
def get_profile(user_id: str):
    return _fixtures["profile"]


@app.get("/gmail/v1/users/{user_id}/messages")
def list_messages(user_id: str, q: str = None, maxResults: int = None):
    return _fixtures["messages_list"]


@app.get("/gmail/v1/users/{user_id}/messages/{message_id}")
def get_message(user_id: str, message_id: str):
    return _fixtures["messages_by_id"].get(message_id, {"id": message_id, "payload": {"headers": []}})


@app.get("/gmail/v1/users/{user_id}/messages/{message_id}/attachments/{attachment_id}")
def get_attachment(user_id: str, message_id: str, attachment_id: str):
    return _fixtures["attachments_by_id"].get(attachment_id, {"data": ""})


# ---------------------------------------------------------------------------
# oauth2 userinfo
# ---------------------------------------------------------------------------

@app.get("/oauth2/v2/userinfo")
def userinfo():
    return _fixtures["userinfo"]


# ---------------------------------------------------------------------------
# Test control
# ---------------------------------------------------------------------------

@app.post("/_stub/seed")
async def seed(request: Request):
    """
    Merge-seed fixture data for the next requests. Body shape:
    {
      "profile": {"emailAddress": "..."},
      "userinfo": {"id": "..."},
      "messages_list": {"messages": [{"id": "m1"}]},
      "messages_by_id": {"m1": {...full Gmail message payload...}},
      "attachments_by_id": {"att1": {"data": "<base64url-encoded bytes>"}}
    }
    """
    body = await request.json()
    for key, value in body.items():
        if key in _fixtures:
            _fixtures[key] = value
    return {"status": "seeded"}


@app.post("/_stub/reset")
def reset():
    _fixtures["profile"] = {"emailAddress": "invoices@example.com"}
    _fixtures["userinfo"] = {"id": "stub-user-123"}
    _fixtures["messages_list"] = {"messages": []}
    _fixtures["messages_by_id"] = {}
    _fixtures["attachments_by_id"] = {}
    return {"status": "reset"}


@app.get("/_stub/health")
def health():
    return {"status": "ok"}
