import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

# Testability hooks, both no-ops in production:
#   GOOGLE_CREDENTIALS_FILE   -- lets E2E tests point at a stub-flavored
#                                credentials.json (with auth_uri/token_uri
#                                pointing at a local Google stub) instead of
#                                the real one. Defaults to "credentials.json".
#   GOOGLE_API_DISCOVERY_URL -- lets E2E tests point googleapiclient's
#                                discovery document fetch at a local stub
#                                server instead of Google's real API roots.
#                                Unset (None) in production, which makes
#                                build() behave exactly as before this change.
_DISCOVERY_URL = os.getenv("GOOGLE_API_DISCOVERY_URL")


def _build_service(service_name: str, version: str, credentials):
    """Thin wrapper around googleapiclient.discovery.build(). Identical to a
    bare build() call unless GOOGLE_API_DISCOVERY_URL is set, in which case
    requests are routed through that discovery document instead of Google's
    real one -- used only by the E2E test suite (see tests/e2e/)."""
    kwargs = {"credentials": credentials}
    if _DISCOVERY_URL:
        kwargs["discoveryServiceUrl"] = _DISCOVERY_URL
        kwargs["static_discovery"] = False
    return build(service_name, version, **kwargs)


class GmailAuth:
    def __init__(self):
        self.credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly",
                       "https://www.googleapis.com/auth/userinfo.profile"]
        self.redirect_uri = os.getenv("REDIRECT_URI")
        self.creds = None
        self.service = None
        self.user_email = None
        self.user_id = None

    def create_flow(self):
        return Flow.from_client_secrets_file(
            self.credentials_file,
            redirect_uri=self.redirect_uri,
            scopes=self.scopes)

    def exchange_code(self, code: str):
        flow = self.create_flow()
        flow.fetch_token(code=code)
        self.creds = flow.credentials
        if self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
        self.initialize_service()

    def initialize_service(self):
        self.service = _build_service("gmail", "v1", self.creds)
        profile = self.service.users().getProfile(userId="me").execute()
        self.user_email = profile.get("emailAddress")

        oauth2_service = _build_service("oauth2", "v2", self.creds)
        userinfo = oauth2_service.userinfo().get().execute()
        self.user_id = userinfo["id"]

    def get_service(self):
        if not self.service:
            raise Exception("Service not authenticated yet.")
        return self.service

    def get_user_db_dict(self):
        return {
            "user_id": self.user_id,
            "email": self.user_email,
            "token_dict": {
                "token": self.creds.token,
                "refresh_token": self.creds.refresh_token,
                "token_uri": self.creds.token_uri,
                "client_id": self.creds.client_id,
                "client_secret": self.creds.client_secret,
                "scopes": self.creds.scopes
            }
        }

    @staticmethod
    def get_service_from_token_dict(token_dict: dict):
        try:
            creds = Credentials(
                token=token_dict.get("token"),
                refresh_token=token_dict.get("refresh_token"),
                token_uri=token_dict.get("token_uri"),
                client_id=token_dict.get("client_id"),
                client_secret=token_dict.get("client_secret"),
                scopes=token_dict.get("scopes")
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return _build_service("gmail", "v1", creds)
        except Exception as e:
            print(f"Error reconstructing credentials: {e}")
            return None
