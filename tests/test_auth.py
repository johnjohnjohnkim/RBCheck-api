from app import models
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def test_transactions_need_a_login(anon_client):
    for path in ("/transactions/summary", "/transactions/month", "/transactions/1"):
        assert anon_client.get(path).status_code == 401
    assert anon_client.post("/transactions", json={}).status_code == 401
    assert anon_client.patch("/transactions/1", json={}).status_code == 401

def test_a_bad_token_is_rejected(anon_client):
    r = anon_client.get("/transactions/month", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401

def test_a_logged_in_user_gets_through(client):
    assert client.get("/transactions/month").status_code == 200

def test_wrong_password_is_rejected(anon_client, client):
    r = anon_client.post("/login", data={"username": TEST_EMAIL, "password": "wrong"})
    assert r.status_code == 403

def test_token_for_a_deleted_user_is_rejected(client, db):
    db.query(models.Users).delete()
    db.commit()
    assert client.get("/transactions/month").status_code == 401

def test_signup_is_closed(anon_client):
    r = anon_client.post("/users", json={"user_email": "x@example.com", "user_password": TEST_PASSWORD})
    assert r.status_code in (404, 405)
