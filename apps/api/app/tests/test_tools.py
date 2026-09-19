import pytest
from fastapi.testclient import TestClient

from app.adapters.llm.base import LLMResult
from app.agent.state import StateError
from app.config import Settings
from app.main import create_app
from app.tests.conftest import send


def test_tools_save_to_lead(client, services, call):
    call_id = call["call_id"]
    send(client, call_id, "yes")
    result = send(client, call_id, "demo information")
    lead = client.get(f"/api/leads/{call['lead_id']}").json()
    assert lead["fields"] == result["collected_fields"] == {"field_1": "demo information"}
    tools = services.agent._tools(services.db.get_call(call_id))
    assert tools.get_next_field(call["lead_id"]).name == "field_2"
    assert not tools.validate_customer_field("field_2", "bad").valid
    with pytest.raises(StateError):
        tools.get_lead("other-lead")


def test_health_and_input_errors(client):
    assert client.get("/health").json()["providers"]["voice"] == "mock"
    assert client.get("/").json()["dashboard"] == "http://localhost:3000"
    assert client.get("/favicon.ico").status_code == 204
    cors = client.get("/health", headers={"Origin": "http://127.0.0.1:3001"})
    assert cors.headers["access-control-allow-origin"] == "http://127.0.0.1:3001"
    assert client.get("/api/leads/missing").status_code == 404
    assert client.get("/api/calls/missing").status_code == 404
    assert client.post("/api/leads", json={"lead_id": "new", "test_data": False}).status_code == 422
    assert client.post("/api/leads", json={"lead_id": "new", "fields": {"field_2": "bad"}}).status_code == 409
    assert client.post("/api/leads", json={"lead_id": "new"}).status_code == 201
    assert client.post("/api/leads", json={"lead_id": "new"}).status_code == 409


def test_browser_adapter_is_the_local_demo_default():
    with TestClient(create_app(Settings(database_url="sqlite:///:memory:"))) as browser_client:
        assert browser_client.get("/health").json()["providers"]["voice"] == "browser"
        call = browser_client.post("/api/calls/start", json={"lead_id": "syn-happy-01"}).json()
        assert call["provider_call_id"].startswith("browser-")


def test_end_route_stops_an_active_browser_or_text_call(client, call):
    ended = client.post(f"/api/calls/{call['call_id']}/end", json={"reason": "CUSTOMER_STOPPED"})
    assert ended.status_code == 200
    assert ended.json()["status"] == "ENDED"
    assert ended.json()["end_reason"] == "CUSTOMER_STOPPED"


def test_webhook_deduplication(client, call):
    event = {"event_id": "evt-1", "call_id": call["call_id"], "type": "transcript.final", "text": "yes"}
    first = client.post("/api/voice/webhook", json=event)
    second = client.post("/api/voice/webhook", json=event)
    assert first.status_code == 200
    assert first.json() == second.json()
    assert second.json()["collected_fields"] == {}
    end = client.post("/api/voice/webhook", json={**event, "event_id": "evt-2", "type": "call.ended"})
    assert end.json()["status"] == "ENDED"


def test_webhook_authentication():
    with TestClient(create_app(Settings(database_url="sqlite:///:memory:", voice_webhook_secret="test-secret"))) as client:
        event = {"event_id": "1", "call_id": "missing", "type": "call.ended"}
        assert client.post("/api/voice/webhook", json=event).status_code == 401
        assert client.post("/api/voice/webhook", json=event,
                           headers={"X-Voice-Webhook-Secret": "test-secret"}).status_code == 404


def test_missing_credentials_fall_back():
    with TestClient(create_app(Settings(database_url="sqlite:///:memory:", llm_provider="openai",
                                       voice_provider="unconfigured"))) as client:
        health = client.get("/health").json()
        assert health["providers"]["llm"] == health["providers"]["voice"] == "mock"
        assert len(health["warnings"]) == 2


def test_dnc_failure_blocks_calls():
    with TestClient(create_app(Settings(database_url="sqlite:///:memory:", dnc_provider="unavailable"))) as client:
        assert client.post("/api/calls/start", json={"lead_id": "syn-happy-01"}).json()["status"] == "BLOCKED_DNC"


def test_llm_failure_hands_off(client, services, call, monkeypatch):
    send(client, call["call_id"], "yes")
    def unavailable(*args, **kwargs):
        raise RuntimeError("simulated outage")
    monkeypatch.setattr(services.llm, "generate_response", unavailable)
    result = send(client, call["call_id"], "some answer")
    assert result["escalation"]["reason"] == "LOW_CONFIDENCE"


def test_llm_cannot_invent_values(client, services, call, monkeypatch):
    send(client, call["call_id"], "yes")
    monkeypatch.setattr(services.llm, "generate_response",
                        lambda *args, **kwargs: LLMResult(value="invented"))
    result = send(client, call["call_id"], "actual answer")
    assert result["collected_fields"] == {}
    assert result["escalation"]["reason"] == "LOW_CONFIDENCE"


def test_persistence_across_restarts(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", field_schema_path="legacy")
    with TestClient(create_app(settings)) as client:
        call_id = client.post("/api/calls/start", json={"lead_id": "demo-energy-001"}).json()["call_id"]
        send(client, call_id, "yes")
        send(client, call_id, "persistent value")
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/calls/{call_id}").json()["current_field"] == "field_2"
        assert client.get("/api/leads/demo-energy-001").json()["fields"]["field_1"] == "persistent value"


def test_voice_start_failure_is_explicit(client, services, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(services.voice, "start_call", unavailable)
    result = client.post("/api/calls/start", json={"lead_id": "demo-energy-001"}).json()
    assert result["status"] == "ENDED"
    assert result["end_reason"] == "VOICE_PROVIDER_FAILURE"


def test_voice_transfer_failure_preserves_context(client, services, call, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(services.voice, "transfer_call", unavailable)
    result = send(client, call["call_id"], "human please")
    assert result["status"] == "HANDOFF"
    assert "failed" in result["provider_error"]
    assert result["escalation"]["call_id"] == call["call_id"]


def test_configurable_schema_and_prompt(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text('[{"name":"provided_test_field","step":"test","question":"Test value?"}]')
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Custom synthetic test prompt")
    settings = Settings(database_url="sqlite:///:memory:", field_schema_path=str(schema),
                        system_prompt_path=str(prompt))
    with TestClient(create_app(settings)) as client:
        call_id = client.post("/api/calls/start", json={"lead_id": "demo-energy-001"}).json()["call_id"]
        assert send(client, call_id, "yes")["current_field"] == "provided_test_field"
        assert client.app.state.services.agent.prompt == "Custom synthetic test prompt"
        assert not client.get("/api/journey/fields").json()["demo_only"]


def test_openai_adapter_with_mock_http(monkeypatch):
    import httpx
    from app.adapters.llm.openai import OpenAILLMProvider

    original_client = httpx.Client
    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"value":"test","confidence":0.9,"understood":true,"handoff_required":false}'
        }}]})
    monkeypatch.setattr(httpx, "Client",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    provider = OpenAILLMProvider("synthetic-test-key", "test-model")
    result = provider.generate_response("Test prompt", [{"role": "user", "content": "test"}],
                                        [], {"field": {"name": "field_1"}})
    assert result.value == "test"
    assert result.confidence == 0.9
