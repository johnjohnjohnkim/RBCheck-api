import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import READ_TOKEN, WRITE_TOKEN, bearer

from app import models
from app.config import Env
from app.database import get_db
from app.main import app

PUBLIC_ROUTES = {"/healthz"}


@pytest.fixture()
def anonymous():
    """A client with no token. No database override: a request that reaches the
    database layer without a valid token would fail here, which is the point."""
    return TestClient(app)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def db_override(Session):
    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()


def routes():
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path not in PUBLIC_ROUTES:
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route.path.replace("{id}", "1")


def test_every_data_route_is_found_by_the_walk():
    found = {path for _, path in routes()}
    assert {"/transactions/summary", "/insights/today", "/ingest/batch", "/ingest/cursor"} <= found


@pytest.mark.parametrize("method,path", list(routes()))
def test_no_token_is_401_on_every_route(anonymous, method, path):
    response = anonymous.request(method, path, json={} if method in ("POST", "PATCH") else None)
    assert response.status_code == 401, f"{method} {path}"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("headers", [
    bearer("not-the-token"),
    bearer(""),
    {"Authorization": f"Basic {READ_TOKEN}"},
    {"Authorization": READ_TOKEN},
    bearer(READ_TOKEN + "x"),
    bearer(READ_TOKEN[:-1]),
])
def test_bad_credentials_are_401(anonymous, headers):
    assert anonymous.get("/transactions/summary", headers=headers).status_code == 401


def test_the_read_token_reads(db_override):
    client = TestClient(app, headers=bearer(READ_TOKEN))
    assert client.get("/transactions/summary").status_code == 200
    assert client.get("/transactions/").status_code == 200
    assert client.get("/insights/history").status_code == 200


def test_the_read_token_cannot_write(db_override):
    client = TestClient(app, headers=bearer(READ_TOKEN))
    body = {"transaction_datetime": "2026-07-04T12:00:00", "amount": "5.00", "place": "X",
            "transaction_type": "CC Purchase"}
    assert client.post("/transactions", json=body).status_code == 403
    assert client.patch("/transactions/1", json={"place": "Y"}).status_code == 403
    assert client.post("/ingest/batch", json={"transactions": []}).status_code == 403
    assert client.get("/ingest/cursor").status_code == 403


def test_the_write_token_writes_and_reads(db_override):
    client = TestClient(app, headers=bearer(WRITE_TOKEN))
    body = {"transaction_datetime": "2026-07-04T12:00:00", "amount": "5.00", "place": "X",
            "transaction_type": "CC Purchase"}
    assert client.post("/transactions", json=body).status_code == 201
    assert client.get("/transactions/").status_code == 200
    assert client.get("/ingest/cursor").status_code == 200


def test_docs_and_schema_are_not_served(anonymous):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert anonymous.get(path).status_code == 404, path


def test_health_check_needs_no_token_and_reveals_nothing(anonymous):
    response = anonymous.get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_cors_allows_the_configured_origins_only(anonymous):
    ask = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    allowed = anonymous.options("/transactions/summary", headers={"Origin": "https://site.example", **ask})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://site.example"
    assert "access-control-allow-credentials" not in allowed.headers

    for origin in ("https://evil.example", "https://site.example.evil.com", "http://localhost:3000"):
        denied = anonymous.options("/transactions/summary", headers={"Origin": origin, **ask})
        assert "access-control-allow-origin" not in denied.headers, origin


def test_missing_tokens_stop_the_app_from_starting(monkeypatch):
    monkeypatch.delenv("READ_TOKEN")
    monkeypatch.delenv("WRITE_TOKEN")
    with pytest.raises(ValidationError):
        Env(_env_file=None)


def test_weak_or_identical_tokens_are_rejected():
    with pytest.raises(ValidationError):
        Env(READ_TOKEN="short", WRITE_TOKEN=WRITE_TOKEN)
    with pytest.raises(ValidationError):
        Env(READ_TOKEN=READ_TOKEN, WRITE_TOKEN=READ_TOKEN)


def test_cors_origins_are_parsed_and_trimmed():
    assert Env(CORS_ORIGINS=" https://a.example , http://b.example ,").cors_origins == [
        "https://a.example", "http://b.example"]


def test_every_write_route_refuses_the_read_token(db_override):
    client = TestClient(app, headers=bearer(READ_TOKEN))
    walked = 0
    for method, path in routes():
        if method == "GET" and not path.startswith("/ingest"):
            continue
        walked += 1
        response = client.request(method, path, json={} if method in ("POST", "PATCH") else None)
        assert response.status_code == 403, f"{method} {path}"
    assert walked >= 4


def test_every_read_route_accepts_the_read_token(db_override):
    client = TestClient(app, headers=bearer(READ_TOKEN))
    walked = 0
    for method, path in routes():
        if method != "GET" or path.startswith("/ingest"):
            continue
        walked += 1
        assert client.request(method, path).status_code not in (401, 403), path
    assert walked >= 10


def test_health_check_answers_head_too(anonymous):
    assert anonymous.head("/healthz").status_code == 200


def test_cors_origins_must_be_plain_origins():
    for bad in ("*", "https://site.example/", "https://*.example", "site.example", "https://a.example/path"):
        with pytest.raises(ValidationError):
            Env(CORS_ORIGINS=bad)
    assert Env(CORS_ORIGINS="https://a.example,http://127.0.0.1:3000").cors_origins == [
        "https://a.example", "http://127.0.0.1:3000"]


def test_tokens_with_surrounding_whitespace_are_rejected():
    with pytest.raises(ValidationError):
        Env(READ_TOKEN=" " * 30, WRITE_TOKEN=WRITE_TOKEN)
    with pytest.raises(ValidationError):
        Env(READ_TOKEN=READ_TOKEN + " ", WRITE_TOKEN=WRITE_TOKEN)
