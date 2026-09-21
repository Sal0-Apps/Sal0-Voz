import pytest
from app import storage as s

@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "DATA", tmp_path / "data")
    s.init()
    return s.DATA

@pytest.fixture
def client(data, monkeypatch):
    monkeypatch.setenv("SAL0_DISABLE_WORKER", "1")
    from app.main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        yield client

@pytest.fixture
def owner(client):
    assert client.post("/api/auth/setup", json={"password": "test-password-123"}).status_code == 200
    return client

