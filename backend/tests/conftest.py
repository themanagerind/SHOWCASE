import os

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://showcase:showcase@localhost:5432/showcase_test"
)

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from freezegun import freeze_time  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.redis import get_redis  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.sms import get_sms_sender  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def engine():
    url = os.environ["DATABASE_URL"]
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")  # tests always run against the real migration
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """Each test runs in a transaction that is rolled back; service-level commit() only releases a savepoint."""
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


class FakeSms:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_otp(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))

    def last_code(self, phone: str) -> str:
        return [c for p, c in self.sent if p == phone][-1]


@pytest.fixture
def sms():
    return FakeSms()


@pytest.fixture
def client(db, redis, sms):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_sms_sender] = lambda: sms
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def frozen():
    with freeze_time("2026-10-17 10:00:00", tick=False) as f:
        yield f


@pytest.fixture
def login(client, sms):
    """Logs a phone in via the real OTP flow and returns the token response JSON."""

    def _login(phone: str = "9876543210") -> dict:
        r = client.post("/api/v1/auth/otp/request", json={"phone": phone})
        assert r.status_code == 200, r.text
        norm = r.json()["phone"]
        r = client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": sms.last_code(norm)})
        assert r.status_code == 200, r.text
        return r.json()

    return _login


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def trial_off(request):
    """Most tests attach subscriptions themselves, so the auto-started free trial is off unless a test enables it."""
    if "db" not in request.fixturenames:
        yield
        return
    db = request.getfixturevalue("db")
    db.execute(text("UPDATE platform_settings SET value = jsonb_set(value, '{enabled}', 'false') WHERE key = 'trial'"))
    yield


def set_setting(db, key: str, value: dict) -> None:
    import json

    db.execute(text("UPDATE platform_settings SET value = CAST(:v AS jsonb) WHERE key = :k"), {"k": key, "v": json.dumps(value)})
    db.flush()
