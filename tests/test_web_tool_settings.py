from fastapi.testclient import TestClient

from myruflo.config import Config
from myruflo.web import tool_settings
from myruflo.web.db import _connect
from tests.conftest import register


def test_admin_can_toggle_a_tool(client: TestClient, app_config: Config):
    register(client, "Admin", "admin@example.com")
    response = client.post("/admin/tools/read_file/toggle", follow_redirects=False)
    assert response.status_code == 303

    conn = _connect(app_config.app_db_path)
    try:
        enabled = tool_settings.load_enabled_tools(conn)
    finally:
        conn.close()
    assert "read_file" not in enabled


def test_non_admin_cannot_toggle_a_tool(client: TestClient):
    register(client, "Admin", "admin@example.com")
    register(client, "Bob", "bob@example.com")
    response = client.post("/admin/tools/read_file/toggle")
    assert response.status_code == 403


def test_tools_page_lists_all_toggleable_tools(client: TestClient):
    register(client, "Admin", "admin@example.com")
    response = client.get("/admin/tools")
    assert response.status_code == 200
    for name in tool_settings.TOGGLEABLE_TOOLS:
        assert name in response.text
