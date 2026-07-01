"""Chat routes, tested with Orchestrator.run monkeypatched so nothing here
calls the real Anthropic API (matches the rest of the suite's offline style).
"""
import base64
import sqlite3

from fastapi.testclient import TestClient

from myruflo.agents.agent import AgentResult
from myruflo.config import Config
from myruflo.llm.client import LLMClient, LLMResponse
from myruflo.swarm.orchestrator import Orchestrator, SwarmReport
from tests.conftest import register

# A valid 1x1 transparent PNG, used to exercise the image-attachment path.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _fake_run(self, task, force_swarm=None, *, enabled_tools=None, image_attachments=None):
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

    response = client.post(f"/chat/{conversation_id}/message", data={"text": "what is 2+2?", "mode": "auto"})
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


def _new_conversation(client: TestClient) -> str:
    created = client.post("/chat/new", follow_redirects=False)
    return created.headers["location"].rsplit("/", 1)[-1]


def test_uploading_a_text_file_is_inlined_and_recorded(client: TestClient, app_config: Config, monkeypatch):
    captured = {}

    def fake_run(self, task, force_swarm=None, *, enabled_tools=None, image_attachments=None):
        captured["task"] = task
        captured["image_attachments"] = image_attachments
        return SwarmReport(
            task=task,
            pipeline=["generalist"],
            results=[AgentResult(role="generalist", task=task, final_text="ok", turns_used=1, transcript=[])],
        )

    monkeypatch.setattr(Orchestrator, "run", fake_run)

    register(client, "Admin", "admin@example.com")
    conversation_id = _new_conversation(client)

    response = client.post(
        f"/chat/{conversation_id}/message",
        data={"text": "what does this file say?", "mode": "auto"},
        files=[("files", ("notes.txt", b"hello world", "text/plain"))],
    )
    assert response.status_code == 200
    assert "notes.txt" in captured["task"]
    assert "hello world" in captured["task"]
    assert captured["image_attachments"] is None

    conn = sqlite3.connect(app_config.app_db_path)
    conn.row_factory = sqlite3.Row
    try:
        atts = conn.execute("SELECT * FROM attachments").fetchall()
    finally:
        conn.close()
    assert len(atts) == 1
    assert atts[0]["filename"] == "notes.txt"
    assert atts[0]["kind"] == "text"


def test_uploading_an_image_becomes_a_vision_block(client: TestClient, monkeypatch):
    captured = {}

    def fake_run(self, task, force_swarm=None, *, enabled_tools=None, image_attachments=None):
        captured["image_attachments"] = image_attachments
        return SwarmReport(
            task=task,
            pipeline=["generalist"],
            results=[AgentResult(role="generalist", task=task, final_text="ok", turns_used=1, transcript=[])],
        )

    monkeypatch.setattr(Orchestrator, "run", fake_run)

    register(client, "Admin", "admin@example.com")
    conversation_id = _new_conversation(client)

    response = client.post(
        f"/chat/{conversation_id}/message",
        data={"text": "what's in this image?", "mode": "auto"},
        files=[("files", ("pic.png", _TINY_PNG, "image/png"))],
    )
    assert response.status_code == 200
    assert captured["image_attachments"] is not None
    assert captured["image_attachments"][0]["type"] == "image"
    assert captured["image_attachments"][0]["source"]["media_type"] == "image/png"


def test_too_many_attachments_rejected(client: TestClient, monkeypatch):
    monkeypatch.setattr(Orchestrator, "run", _fake_run)
    register(client, "Admin", "admin@example.com")
    conversation_id = _new_conversation(client)

    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(6)]
    response = client.post(
        f"/chat/{conversation_id}/message", data={"text": "hi", "mode": "auto"}, files=files
    )
    assert response.status_code == 400


def test_attachment_not_served_to_non_owner(client: TestClient, monkeypatch):
    monkeypatch.setattr(Orchestrator, "run", _fake_run)
    register(client, "Admin", "admin@example.com")
    conversation_id = _new_conversation(client)
    client.post(
        f"/chat/{conversation_id}/message",
        data={"text": "hi", "mode": "auto"},
        files=[("files", ("a.txt", b"hi", "text/plain"))],
    )
    attachment_page = client.get(f"/chat/{conversation_id}")
    assert "a.txt" in attachment_page.text

    register(client, "Bob", "bob@example.com")  # switches the active session to Bob
    response = client.get(f"/chat/{conversation_id}/attachments/1")
    assert response.status_code == 404


def test_enhance_endpoint_rewrites_prompt(client: TestClient, monkeypatch):
    def fake_call(self, **kwargs):
        return LLMResponse(text="A clearer version.", tool_calls=[], stop_reason="end_turn", raw_content=[])

    monkeypatch.setattr(LLMClient, "call", fake_call)

    register(client, "Admin", "admin@example.com")
    conversation_id = _new_conversation(client)

    response = client.post(f"/chat/{conversation_id}/enhance", json={"text": "fix bug"})
    assert response.status_code == 200
    assert response.json()["text"] == "A clearer version."
