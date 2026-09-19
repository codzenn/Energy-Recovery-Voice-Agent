import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    # Unit tests exercise the provider webhook contract with its deterministic
    # transport. The production local-demo default is the browser adapter.
    with TestClient(create_app(Settings(database_url="sqlite:///:memory:", field_schema_path="legacy", voice_provider="mock"))) as test_client:
        yield test_client


@pytest.fixture
def services(client):
    return client.app.state.services


@pytest.fixture
def call(client):
    response = client.post("/api/calls/start", json={"lead_id": "demo-energy-001"})
    assert response.status_code == 200
    return response.json()


def send(client, call_id, text, **kwargs):
    response = client.post(f"/api/calls/{call_id}/message", json={"text": text, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()
