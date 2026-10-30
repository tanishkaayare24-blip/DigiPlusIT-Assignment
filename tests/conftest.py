import os
import tempfile

# Point the app at a throwaway database and disable real AI before the app is imported.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["AI_PROVIDER"] = "none"
os.environ["AI_API_KEY"] = ""
os.environ["LOG_DIR"] = os.path.join(_tmp, "logs")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.seed import reset_demo  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        with SessionLocal() as db:
            reset_demo(db)
        yield c


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session
