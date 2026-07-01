"""Chat routes, tested with Orchestrator.run monkeypatched so nothing here
calls the real Anthropic API (matches the rest of the suite's offline style).
"""
import sqlite3

from fastapi.testclient import TestClient

from myruflo.agents.agent import AgentResult
from myruflo.config import Config
from myruflo.swarm.orchestrator import Orchestrator, SwarmReport
from tests.conftest import register


def _fake_run(self, task, force_swarm=None, *, enabled_tools=None):
    return SwarmReport(
        task=task,
        pipeline=["generalist"],
        results=[AgentResult(role="generalist", task=task, final_text="42", turns_used=1, transcript=[])],
    )


def test_new_conversation_is_reachable_by_its_owner(client: TestClient):
    register(client, "Admin", "admin@example.com")
    created = client.post("/chat/new", follow_redirects=False)
    assert created.status_code == 303
    conversation_url = created.headers["location"]

    page = client.get(conversation_url)
    assert page.status_code == 200


def test_user_cannot_open_another_users_conversation(client: TestClient):
    register(client, "Admin", "admin@example.com")
    created = client.post("/chat/new", follow_redirects=False)
    conversation_url = created.headers["location"]

    register(client, "Bob", "bob@example.com")  # switches the active session to Bob
    response = client.get(conversation_url)
    assert response.status_code == 404


def test_posting_a_message_records_messages_and_task_runs(client: TestClient, app_config: Config, monkeypatch):
    monkeypatch.setattr(Orchestrator, "run", _fake_run)

    register(client, "Admin", "admin@example.com")
    created = client.post("/chat/new", follow_redirects=False)
    conversation_id = created.headers["location"].rsplit("/", 1)[-1]

    response = client.post(f"/chat/{conversation_id}/message", json={"text": "what is 2+2?", "mode": "auto"})
    assert response.status_code == 200
    assert "42" in response.text

    conn = sqlite3.connect(app_config.app_db_path)
    conn.row_factory = sqlite3.Row
    try:
        messages = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
        ).fetchall()
        task_runs = conn.execute("SELECT * FROM task_runs").fetchall()
    finally:
        conn.close()

    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "what is 2+2?"
    assert messages[1]["content"] == "42"
    assert len(task_runs) == 1
    assert task_runs[0]["agent_role"] == "generalist"
    assert task_runs[0]["success"] == 1
