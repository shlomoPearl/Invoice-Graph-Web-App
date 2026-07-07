import os
from cryptography.fernet import Fernet

# Must be set before `import crypto` (module-level check raises RuntimeError otherwise)
os.environ.setdefault("ENC_KEY", Fernet.generate_key().decode())

# Used by db.py at import time
os.environ.setdefault("DB_URL", "sqlite:///:memory:")

# Used by main.py / SessionMiddleware
os.environ.setdefault("KEY", "test-secret-key-for-sessions")

# Used by gmail_auth.py
os.environ.setdefault("REDIRECT_URI", "http://testserver/oauth2callback")

import sys
import types
import pytest

# ---------------------------------------------------------------------------
# Stub out `transformers` so that importing layoutmlv3_model.py / bill.py
# never requires the real (huge) transformers/torch install or a HF model
# download. Unit tests should never load the actual ML pipeline -- that's
# reserved for a separate, manually-run model-eval suite. Individual tests
# that need to control pipeline behavior monkeypatch `LayoutModel` directly.
# ---------------------------------------------------------------------------
if "transformers" not in sys.modules:
    fake_transformers = types.ModuleType("transformers")

    def _fake_pipeline(*args, **kwargs):
        raise RuntimeError(
            "The real HF pipeline should never be invoked in unit tests. "
            "Patch LayoutModel or the pipeline call in your test instead."
        )

    fake_transformers.pipeline = _fake_pipeline
    sys.modules["transformers"] = fake_transformers


@pytest.fixture
def sample_bill_dict():
    """A small, deterministic bill_dict as produced by ReadBill.parser()."""
    return {
        "01/2024": 150.0,
        "02/2024": 200.5,
        "03/2024": 99.99,
    }