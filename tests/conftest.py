from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myruflo.config import Config
from myruflo.web.app import create_app


@pytest.fixture
def app_config(tmp_path: Path) -> Config:
    config = Config(
        api_key="sk-ant-test-key",
        workspace=tmp_path / "workspace",
        data_dir=tmp_path / "data",
        web_secret_key="test-secret-key",
    )
    config.workspace.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


@pytest.fixture
def client(app_config: Config) -> TestClient:
    app = create_app(app_config)
    return TestClient(app)


def register(client: TestClient, name: str, email: str, password: str = "password123") -> None:
    response = client.post("/register", json={"name": name, "email": email, "password": password})
    assert response.status_code == 200, response.text
