import os
import shutil
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="elm-test-")
# SQLite by default. Set ELM_TEST_DATABASE_URL to an EMPTY throwaway MySQL/MariaDB database (never proflow_uat itself)
# to run the suite on the target engine, e.g. mysql+pymysql://elm:pw@localhost:3309/elm_test?charset=utf8mb4
os.environ["ELM_DATABASE_URL"] = os.environ.get("ELM_TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["ELM_STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["ELM_PKI_DIR"] = f"{_tmp}/pki"
os.environ["ELM_ENVIRONMENT"] = "dev"
os.environ["ELM_SEED_DEMO_DATA"] = "true"
os.environ["ELM_ONLYOFFICE_JWT_SECRET"] = "test-oo-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PW = "Elm@12345"


@pytest.fixture(scope="session")
def client_factory():
    with TestClient(app) as base:  # triggers startup (create_all + seed)
        def make(username: str | None = None) -> TestClient:
            c = TestClient(app)
            if username:
                r = c.post("/api/v1/auth/login", json={"username": username, "password": PW})
                assert r.status_code == 200, r.text
                c.headers["X-CSRF-Token"] = c.cookies.get("elm_csrf")
            return c

        yield make
    shutil.rmtree(_tmp, ignore_errors=True)
