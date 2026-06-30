import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()


class GmailAuth:
    def __init__(self):
        self.credentials_file = "credentials.json"
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
        self.service = build("gmail", "v1", credentials=self.creds)
        profile = self.service.users().getProfile(userId="me").execute()
        self.user_email = profile.get("emailAddress")

        oauth2_service = build('oauth2', 'v2', credentials=self.creds)
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
            return build("gmail", "v1", credentials=creds)
        except Exception as e:
            print(f"Error reconstructing credentials: {e}")
            return None
