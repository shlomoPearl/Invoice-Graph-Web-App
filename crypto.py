import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
FERNET_KEY = os.getenv("ENC_KEY")
if not FERNET_KEY:
    raise RuntimeError("ENC_KEY missing")

fernet = Fernet(FERNET_KEY.encode())


def encrypt_bytes(data: bytes) -> bytes:
    return fernet.encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    return fernet.decrypt(token)
