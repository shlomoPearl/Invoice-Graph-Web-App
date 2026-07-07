import pytest
from cryptography.fernet import InvalidToken
import crypto


class TestEncryptDecryptRoundTrip:
    def test_round_trip_returns_original_bytes(self):
        original = b"super secret token payload"
        encrypted = crypto.encrypt_bytes(original)
        assert encrypted != original
        assert crypto.decrypt_bytes(encrypted) == original

    def test_round_trip_empty_bytes(self):
        encrypted = crypto.encrypt_bytes(b"")
        assert crypto.decrypt_bytes(encrypted) == b""

    def test_round_trip_json_like_payload(self):
        import json
        payload = json.dumps({"token": "abc", "refresh_token": "xyz"}).encode()
        encrypted = crypto.encrypt_bytes(payload)
        assert json.loads(crypto.decrypt_bytes(encrypted).decode()) == {
            "token": "abc", "refresh_token": "xyz"
        }

    def test_encrypting_same_plaintext_twice_yields_different_ciphertext(self):
        # Fernet includes a random IV/timestamp, so ciphertexts should differ
        # even for identical plaintext -- this is a property worth locking in.
        a = crypto.encrypt_bytes(b"same input")
        b = crypto.encrypt_bytes(b"same input")
        assert a != b


class TestDecryptFailureModes:
    def test_decrypting_garbage_raises(self):
        with pytest.raises(InvalidToken):
            crypto.decrypt_bytes(b"not a valid fernet token")

    def test_decrypting_tampered_token_raises(self):
        token = crypto.encrypt_bytes(b"original data")
        tampered = token[:-5] + b"xxxxx"
        with pytest.raises(InvalidToken):
            crypto.decrypt_bytes(tampered)


class TestMissingKeyAtImport:
    def test_missing_enc_key_raises_runtime_error(self, monkeypatch):
        import importlib
        import sys

        monkeypatch.delenv("ENC_KEY", raising=False)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        sys.modules.pop("crypto", None)
        with pytest.raises(RuntimeError, match="ENC_KEY missing"):
            importlib.import_module("crypto")
        sys.modules.pop("crypto", None)