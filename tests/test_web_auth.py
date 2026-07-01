import sqlite3

from fastapi.testclient import TestClient

from myruflo.config import Config
from tests.conftest import register


def _roles(app_config: Config) -> list[str]:
    conn = sqlite3.connect(app_config.app_db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [row["role"] for row in conn.execute("SELECT role FROM users ORDER BY id")]
    finally:
        conn.close()


def test_first_registered_user_is_admin_second_is_not(client: TestClient, app_config: Config):
    register(client, "Admin", "admin@example.com")
    register(client, "Bob", "bob@example.com")
    assert _roles(app_config) == ["admin", "user"]


def test_admin_can_reach_admin_dashboard(client: TestClient):
    register(client, "Admin", "admin@example.com")
    response = client.get("/admin")
    assert response.status_code == 200


def test_non_admin_is_rejected_from_admin_dashboard(client: TestClient):
    register(client, "Admin", "admin@example.com")
    register(client, "Bob", "bob@example.com")  # registering logs Bob in, replacing the session
    response = client.get("/admin")
    assert response.status_code == 403


def test_bad_login_does_not_authenticate(client: TestClient):
    register(client, "Admin", "admin@example.com")
    client.post("/logout", follow_redirects=False)

    response = client.post("/login", json={"email": "admin@example.com", "password": "wrong"})
    assert response.status_code == 401

    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/login"


def test_logout_clears_session(client: TestClient):
    register(client, "Admin", "admin@example.com")
    assert client.get("/", follow_redirects=False).status_code == 200

    client.post("/logout", follow_redirects=False)
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/login"


def test_duplicate_email_rejected(client: TestClient):
    register(client, "Admin", "admin@example.com")
    response = client.post(
        "/register", json={"name": "Someone Else", "email": "admin@example.com", "password": "password123"}
    )
    assert response.status_code == 400
