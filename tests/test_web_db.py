from pathlib import Path

from myruflo.web import db, tool_settings


def test_init_app_db_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "app.db"
    db.init_app_db(db_path)
    db.init_app_db(db_path)  # must not raise on a second call

    conn = db._connect(db_path)
    try:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"users", "conversations", "messages", "task_runs", "tool_settings"} <= tables
    finally:
        conn.close()


def test_seed_tool_settings_defaults(tmp_path: Path):
    conn = db._connect(tmp_path / "app.db")
    try:
        conn.executescript(db.SCHEMA)
        tool_settings.seed_tool_settings(conn)
        state = {row["tool_name"]: row["enabled"] for row in conn.execute("SELECT * FROM tool_settings")}
        assert state["run_shell"] == 0
        assert state["read_file"] == 1
        assert set(state) == set(tool_settings.TOGGLEABLE_TOOLS)
    finally:
        conn.close()


def test_reseeding_does_not_clobber_existing_toggle(tmp_path: Path):
    conn = db._connect(tmp_path / "app.db")
    try:
        conn.executescript(db.SCHEMA)
        conn.execute(
            "INSERT INTO users (id, name, email, password_hash, role, created_at) "
            "VALUES (1, 'Admin', 'admin@example.com', 'x', 'admin', '2026-01-01T00:00:00+00:00')"
        )
        tool_settings.seed_tool_settings(conn)
        tool_settings.toggle(conn, "read_file", admin_user_id=1)  # disable it via a real admin action first

        tool_settings.seed_tool_settings(conn)  # simulate a second app startup

        enabled = tool_settings.load_enabled_tools(conn)
        assert "read_file" not in enabled
    finally:
        conn.close()
