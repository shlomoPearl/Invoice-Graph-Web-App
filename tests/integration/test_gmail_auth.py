from unittest.mock import MagicMock
import pytest

import gmail_auth
from gmail_auth import GmailAuth


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setenv("REDIRECT_URI", "http://testserver/oauth2callback")


class TestCreateFlow:
    def test_create_flow_uses_credentials_file_redirect_uri_and_scopes(self, monkeypatch):
        mock_flow_cls = MagicMock()
        monkeypatch.setattr(gmail_auth, "Flow", mock_flow_cls)

        auth = GmailAuth()
        auth.create_flow()

        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            "credentials.json",
            redirect_uri="http://testserver/oauth2callback",
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/userinfo.profile",
            ],
        )

    def test_create_flow_returns_the_flow_instance(self, monkeypatch):
        mock_flow_cls = MagicMock()
        expected_flow = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = expected_flow
        monkeypatch.setattr(gmail_auth, "Flow", mock_flow_cls)

        auth = GmailAuth()
        assert auth.create_flow() is expected_flow


class TestExchangeCode:
    def _make_auth_with_mocked_flow(self, monkeypatch, creds):
        mock_flow = MagicMock()
        mock_flow.credentials = creds
        monkeypatch.setattr(GmailAuth, "create_flow", lambda self: mock_flow)
        monkeypatch.setattr(GmailAuth, "initialize_service", lambda self: None)
        return mock_flow

    def test_fetch_token_called_with_provided_code(self, monkeypatch):
        creds = MagicMock(expired=False, refresh_token=None)
        mock_flow = self._make_auth_with_mocked_flow(monkeypatch, creds)

        auth = GmailAuth()
        auth.exchange_code("auth-code-123")

        mock_flow.fetch_token.assert_called_once_with(code="auth-code-123")

    def test_credentials_stored_from_flow(self, monkeypatch):
        creds = MagicMock(expired=False, refresh_token=None)
        self._make_auth_with_mocked_flow(monkeypatch, creds)

        auth = GmailAuth()
        auth.exchange_code("code")
        assert auth.creds is creds

    def test_expired_credentials_with_refresh_token_are_refreshed(self, monkeypatch):
        creds = MagicMock(expired=True, refresh_token="refresh-abc")
        self._make_auth_with_mocked_flow(monkeypatch, creds)
        mock_request_cls = MagicMock()
        monkeypatch.setattr(gmail_auth, "Request", mock_request_cls)

        auth = GmailAuth()
        auth.exchange_code("code")

        creds.refresh.assert_called_once()

    def test_expired_credentials_without_refresh_token_are_not_refreshed(self, monkeypatch):
        creds = MagicMock(expired=True, refresh_token=None)
        self._make_auth_with_mocked_flow(monkeypatch, creds)

        auth = GmailAuth()
        auth.exchange_code("code")

        creds.refresh.assert_not_called()

    def test_non_expired_credentials_are_not_refreshed(self, monkeypatch):
        creds = MagicMock(expired=False, refresh_token="refresh-abc")
        self._make_auth_with_mocked_flow(monkeypatch, creds)

        auth = GmailAuth()
        auth.exchange_code("code")

        creds.refresh.assert_not_called()

    def test_initialize_service_is_called_after_token_exchange(self, monkeypatch):
        creds = MagicMock(expired=False, refresh_token=None)
        mock_flow = MagicMock()
        mock_flow.credentials = creds
        monkeypatch.setattr(GmailAuth, "create_flow", lambda self: mock_flow)

        init_called = []
        monkeypatch.setattr(GmailAuth, "initialize_service", lambda self: init_called.append(True))

        auth = GmailAuth()
        auth.exchange_code("code")
        assert init_called == [True]


class TestInitializeService:
    def test_populates_service_email_and_user_id(self, monkeypatch):
        mock_build = MagicMock()
        gmail_service = MagicMock()
        gmail_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "user@example.com"
        }
        oauth2_service = MagicMock()
        oauth2_service.userinfo.return_value.get.return_value.execute.return_value = {
            "id": "1234567890"
        }
        # build() is called twice: once for "gmail" v1, once for "oauth2" v2
        mock_build.side_effect = [gmail_service, oauth2_service]
        monkeypatch.setattr(gmail_auth, "build", mock_build)

        auth = GmailAuth()
        auth.creds = MagicMock()
        auth.initialize_service()

        assert auth.service is gmail_service
        assert auth.user_email == "user@example.com"
        assert auth.user_id == "1234567890"

    def test_build_called_with_correct_service_names(self, monkeypatch):
        mock_build = MagicMock()
        gmail_service = MagicMock()
        gmail_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "x@y.com"
        }
        oauth2_service = MagicMock()
        oauth2_service.userinfo.return_value.get.return_value.execute.return_value = {"id": "1"}
        mock_build.side_effect = [gmail_service, oauth2_service]
        monkeypatch.setattr(gmail_auth, "build", mock_build)

        auth = GmailAuth()
        auth.creds = MagicMock()
        auth.initialize_service()

        calls = mock_build.call_args_list
        assert calls[0].args == ("gmail", "v1")
        assert calls[1].args == ("oauth2", "v2")

    def test_missing_email_address_key_sets_none(self, monkeypatch):
        # profile.get("emailAddress") on a dict missing that key -> None,
        # rather than raising KeyError.
        mock_build = MagicMock()
        gmail_service = MagicMock()
        gmail_service.users.return_value.getProfile.return_value.execute.return_value = {}
        oauth2_service = MagicMock()
        oauth2_service.userinfo.return_value.get.return_value.execute.return_value = {"id": "1"}
        mock_build.side_effect = [gmail_service, oauth2_service]
        monkeypatch.setattr(gmail_auth, "build", mock_build)

        auth = GmailAuth()
        auth.creds = MagicMock()
        auth.initialize_service()

        assert auth.user_email is None


class TestGetService:
    def test_raises_when_service_not_yet_authenticated(self):
        auth = GmailAuth()
        with pytest.raises(Exception, match="Service not authenticated yet."):
            auth.get_service()

    def test_returns_service_when_authenticated(self):
        auth = GmailAuth()
        fake_service = MagicMock()
        auth.service = fake_service
        assert auth.get_service() is fake_service


class TestGetUserDbDict:
    def test_builds_expected_dict_shape(self):
        auth = GmailAuth()
        auth.user_id = "user-123"
        auth.user_email = "user@example.com"
        auth.creds = MagicMock(
            token="access-token",
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="client-id",
            client_secret="client-secret",
            scopes=["scope1", "scope2"],
        )

        result = auth.get_user_db_dict()

        assert result == {
            "user_id": "user-123",
            "email": "user@example.com",
            "token_dict": {
                "token": "access-token",
                "refresh_token": "refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "scopes": ["scope1", "scope2"],
            },
        }


class TestGetServiceFromTokenDict:
    def test_builds_service_from_valid_token_dict(self, monkeypatch):
        mock_creds_cls = MagicMock()
        mock_creds_instance = MagicMock(expired=False, refresh_token="refresh-abc")
        mock_creds_cls.return_value = mock_creds_instance
        monkeypatch.setattr(gmail_auth, "Credentials", mock_creds_cls)

        mock_build = MagicMock()
        fake_service = MagicMock()
        mock_build.return_value = fake_service
        monkeypatch.setattr(gmail_auth, "build", mock_build)

        token_dict = {
            "token": "t", "refresh_token": "r", "token_uri": "u",
            "client_id": "ci", "client_secret": "cs", "scopes": ["s"],
        }
        result = GmailAuth.get_service_from_token_dict(token_dict)

        assert result is fake_service
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds_instance)

    def test_expired_credentials_are_refreshed_before_building_service(self, monkeypatch):
        mock_creds_cls = MagicMock()
        mock_creds_instance = MagicMock(expired=True, refresh_token="refresh-abc")
        mock_creds_cls.return_value = mock_creds_instance
        monkeypatch.setattr(gmail_auth, "Credentials", mock_creds_cls)
        monkeypatch.setattr(gmail_auth, "build", MagicMock())

        GmailAuth.get_service_from_token_dict({"token": "t"})

        mock_creds_instance.refresh.assert_called_once()

    def test_malformed_token_dict_returns_none_not_raise(self, monkeypatch):
        mock_creds_cls = MagicMock(side_effect=ValueError("bad token data"))
        monkeypatch.setattr(gmail_auth, "Credentials", mock_creds_cls)

        result = GmailAuth.get_service_from_token_dict({"garbage": "data"})
        assert result is None

    def test_empty_dict_does_not_raise_and_returns_none_or_service(self, monkeypatch):
        # token_dict.get(...) on an empty dict returns None for every field --
        # Credentials(...) itself may or may not accept all-None kwargs
        # depending on the real google-auth version. Either a clean service
        # build or a caught exception -> None is acceptable; an uncaught
        # exception propagating out is not.
        mock_creds_cls = MagicMock()
        mock_creds_instance = MagicMock(expired=False, refresh_token=None)
        mock_creds_cls.return_value = mock_creds_instance
        monkeypatch.setattr(gmail_auth, "Credentials", mock_creds_cls)
        monkeypatch.setattr(gmail_auth, "build", MagicMock())

        result = GmailAuth.get_service_from_token_dict({})
        assert result is not None  # build() mock returns a MagicMock, not None