"""
Integration tests combined storage.py db.py model.py and crypto.py.
Requires Docker to be running locally / in CI.
"""
import importlib
import os
import sys
from time import sleep
from datetime import datetime, timedelta, timezone
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="module")
def postgres_container():
    # handle cleanup automatically
    with PostgresContainer("postgres:15-alpine") as container: 
        yield container


@pytest.fixture(scope="module")
def db_module(postgres_container):
    """
    Import db.py / model.py / storage.py against the real Postgres container,
    then create all tables. Yields the three imported modules as a tuple.
    """
    os.environ["DB_URL"] = postgres_container.get_connection_url()
    # Force re-import of db, model, storage to pick up the new DB_URL
    # and avoid caching from previous tests
    for mod_name in ("db", "model", "storage"):
        sys.modules.pop(mod_name, None)

    db = importlib.import_module("db")
    model = importlib.import_module("model")
    storage = importlib.import_module("storage")

    db.Base.metadata.create_all(bind=db.engine)
    yield db, model, storage
    db.Base.metadata.drop_all(bind=db.engine)


@pytest.fixture
def db_session(db_module):
    """A fresh Session per test, with tables wiped clean afterward."""
    db, model, storage = db_module
    session = db.SessionLocal()
    yield session
    session.rollback()
    session.query(model.SessionToken).delete()
    session.query(model.User).delete()
    session.commit()
    session.close()


class TestSaveAndLoadUserToken:
    def test_save_then_load__token_dict(self, db_module, db_session):
        db, model, storage = db_module
        token_dict = {"token": "abc", "refresh_token": "xyz", "scopes": ["a", "b"]}
        storage.save_user_token(db_session, "user1", "user1@test.com", token_dict)
        result = storage.load_user_token(db_session, "user1")
        assert result == token_dict

    def test_token_is_encrypted_at_rest(self, db_module, db_session):
        db, model, storage = db_module
        token_dict = {"token": "super-secret-value"}
        storage.save_user_token(db_session, "user1", "user1@test.com", token_dict)
        row = db_session.query(model.User).filter_by(g_id="user1").one()
        assert b"super-secret-value" not in row.token

    # when user change their email their g_id remains the same
    def test_saving_again_upserts_rather_than_duplicates(self, db_module, db_session):
        db, model, storage = db_module
        storage.save_user_token(db_session, "user1", "old@test.com", {"token": "old"})
        storage.save_user_token(db_session, "user1", "new@test.com", {"token": "new"})

        count = db_session.query(model.User).filter_by(g_id="user1").count()
        assert count == 1
        row = db_session.query(model.User).filter_by(g_id="user1").one()
        assert row.email == "new@test.com"
        assert storage.load_user_token(db_session, "user1") == {"token": "new"}

    def test_expired_token_returns_none(self, db_module, db_session):
        db, model, storage = db_module
        storage.save_user_token(db_session, "user1", "user1@test.com", {"token": "x"})
        row = db_session.query(model.User).filter_by(g_id="user1").one()
        # Set the expires_at to a time in the past to simulate expiration
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.commit()
        assert storage.load_user_token(db_session, "user1") is None

    def test_inactive_user_returns_none(self, db_module, db_session):
        db, model, storage = db_module
        storage.save_user_token(db_session, "user1", "user1@test.com", {"token": "x"})
        row = db_session.query(model.User).filter_by(g_id="user1").one()
        row.is_active = False
        db_session.commit()
        assert storage.load_user_token(db_session, "user1") is None

    def test_corrupted_ciphertext_returns_none_not_raise(self, db_module, db_session):
        db, model, storage = db_module
        storage.save_user_token(db_session, "user1", "user1@test.com", {"token": "x"})
        row = db_session.query(model.User).filter_by(g_id="user1").one()
        row.token = b"not-a-valid-fernet-token"
        db_session.commit()
        assert storage.load_user_token(db_session, "user1") is None

    def test_unknown_user_id_returns_none(self, db_module, db_session):
        db, model, storage = db_module
        assert storage.load_user_token(db_session, "no-such-user") is None

    def test_load_updates_last_accessed_timestamp(self, db_module, db_session):
        db, model, storage = db_module
        storage.save_user_token(db_session, "user1", "user1@test.com", {"token": "x"})
        row = db_session.query(model.User).filter_by(g_id="user1").one()
        original_last_accessed = row.last_accessed
        sleep(0.2)  # Ensure the timestamp will be different
        storage.load_user_token(db_session, "user1")
        db_session.refresh(row)
        assert row.last_accessed > original_last_accessed

    def test_distinct_users_are_independent(self, db_module, db_session):
        db, model, storage = db_module
        storage.save_user_token(db_session, "user1", "a@test.com", {"token": "a"})
        storage.save_user_token(db_session, "user2", "b@test.com", {"token": "b"})
        assert storage.load_user_token(db_session, "user1") == {"token": "a"}
        assert storage.load_user_token(db_session, "user2") == {"token": "b"}


class TestSessionLifecycle:
    def test_create_then_validate_returns_correct_user(self, db_module, db_session):
        db, model, storage = db_module
        session_id = storage.create_session(db_session, "user1")
        assert storage.validate_session(db_session, session_id) == "user1"

    def test_validate_unknown_session_id_returns_none(self, db_module, db_session):
        db, model, storage = db_module
        assert storage.validate_session(db_session, "does-not-exist") is None

    def test_invalidate_then_validate_returns_none(self, db_module, db_session):
        db, model, storage = db_module
        session_id = storage.create_session(db_session, "user1")
        storage.invalidate_session(db_session, session_id)
        assert storage.validate_session(db_session, session_id) is None

    def test_invalidating_unknown_session_id_does_not_raise(self, db_module, db_session):
        db, model, storage = db_module
        storage.invalidate_session(db_session, "does-not-exist")  # should be a no-op

    def test_expired_session_returns_none(self, db_module, db_session):
        db, model, storage = db_module
        session_id = storage.create_session(db_session, "user1")
        row = db_session.query(model.SessionToken).filter_by(session_id=session_id).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        assert storage.validate_session(db_session, session_id) is None

    def test_multiple_sessions_for_same_user_are_independent(self, db_module, db_session):
        db, model, storage = db_module
        session_a = storage.create_session(db_session, "user1")
        session_b = storage.create_session(db_session, "user1")
        storage.invalidate_session(db_session, session_a)
        assert storage.validate_session(db_session, session_a) is None
        assert storage.validate_session(db_session, session_b) == "user1"


class TestCleanup:
    def test_cleanup_expired_sessions_removes_only_expired_rows(self, db_module, db_session):
        db, model, storage = db_module
        valid_id = storage.create_session(db_session, "user1")
        expired_id = storage.create_session(db_session, "user1")
        expired_row = db_session.query(model.SessionToken).filter_by(session_id=expired_id).one()
        expired_row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        storage.cleanup_expired_sessions(db_session)
        remaining_ids = {
            row.session_id for row in db_session.query(model.SessionToken).all()
        }
        assert valid_id in remaining_ids
        assert expired_id not in remaining_ids

    def test_cleanup_expired_tokens_removes_only_expired_rows(self, db_module, db_session):
        db, model, storage = db_module
        storage.save_user_token(db_session, "valid_user", "v@test.com", {"token": "v"})
        storage.save_user_token(db_session, "expired_user", "e@test.com", {"token": "e"})
        expired_row = db_session.query(model.User).filter_by(g_id="expired_user").one()
        expired_row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.commit()
        storage.cleanup_expired_tokens(db_session)
        remaining_ids = {
            row.g_id for row in db_session.query(model.User).all()
        }
        assert "valid_user" in remaining_ids
        assert "expired_user" not in remaining_ids

    def test_cleanup_with_no_expired_rows_is_a_no_op(self, db_module, db_session):
        db, model, storage = db_module
        storage.create_session(db_session, "user1")
        storage.save_user_token(db_session, "user1", "user1@test.com", {"token": "x"})
        before_sessions = db_session.query(model.SessionToken).count()
        before_users = db_session.query(model.User).count()
        storage.cleanup_expired_sessions(db_session)
        storage.cleanup_expired_tokens(db_session)
        assert db_session.query(model.SessionToken).count() == before_sessions
        assert db_session.query(model.User).count() == before_users