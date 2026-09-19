import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.agent.state import ConversationState, StateError, validate_field
from app.config import Settings
from app.main import create_app
from app.models.journey import DATA_DIR, FieldSpec, JourneyDefinition, load_journey
from app.models.lead import Lead
from app.services.scenario_service import scenarios
from app.tests.conftest import send


@pytest.fixture
def energy(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'energy.db'}",
                        completions_path=str(tmp_path / "completions.json"))
    with TestClient(create_app(settings)) as client:
        yield client


def start(client, lead_id="syn-happy-01"):
    response = client.post("/api/calls/start", json={"lead_id": lead_id})
    assert response.status_code == 200, response.text
    return response.json()["call_id"]


@pytest.mark.parametrize("scenario", [item["scenario"] for item in scenarios()])
def test_scenarios_execute_engine(energy, scenario):
    response = energy.post(f"/api/demo/scenarios/{scenario}/run")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["passed"], result["call"]
    saved = energy.get(f"/api/calls/{result['call']['call_id']}").json()
    assert saved == result["call"]
    if saved["escalation"]:
        assert saved["escalation"]["collected_fields"] == saved["collected_fields"]
        assert saved["escalation"]["remaining_fields"]
        assert saved["escalation"]["transcript"] == saved["transcript"]
    if scenario == "happy_path":
        assert saved["completion_result"]["submission_id"]
        assert saved["collected_fields"]["email"] == "alex.demo@example.test"
        assert "gas_connection_type" not in saved["collected_fields"]
        exported = json.loads(energy.app.state.services.cimet.completions_path.read_text())
        assert exported[0]["payload"]["fields"] == saved["collected_fields"]
        events = {event["event_type"] for event in saved["events"]}
        assert {"CALL_STARTED", "CONSENT_REQUESTED", "CONSENT_GRANTED", "FIELD_REQUESTED",
                "FIELD_CAPTURED", "FIELD_CONFIRMED", "FIELD_VALIDATION_FAILED", "JOURNEY_SUBMITTED",
                "JOURNEY_COMPLETED", "CALL_ENDED"} <= events


def test_dataset_and_definition(energy):
    leads = energy.get("/api/leads").json()
    assert len(leads) == 11
    assert all(lead["synthetic"] for lead in leads)
    definition = energy.get("/api/journeys/energy-demo").json()
    assert definition["synthetic"]
    assert len(definition["fields"]) == 12
    assert len(energy.get("/api/demo/scenarios").json()) == 9
    assert energy.post("/api/demo/scenarios/missing/run").status_code == 404
    raw = json.loads((DATA_DIR / "leads.json").read_text())
    specs = load_journey().fields
    for lead in raw:
        actual_missing = [spec.name for spec in specs if spec.required
                          and spec.active(lead["prefilled_fields"]) and spec.name not in lead["prefilled_fields"]]
        assert actual_missing == lead["missing_fields"]


@pytest.mark.parametrize("kind,value,valid,normalized", [
    ("email", "alex at example dot test", True, "alex@example.test"),
    ("email", "invalid@", False, None),
    ("postcode", "3000", True, "3000"),
    ("postcode", "300", False, None),
    ("date", "2026-02-30", False, None),
    ("date", "2028-02-29", True, "2028-02-29"),
    ("date", "tomorrow", False, None),
    ("phone", "0491570006", True, "0491570006"),
    ("phone", "1234", False, None),
])
def test_deterministic_formats(kind, value, valid, normalized):
    result = validate_field(FieldSpec(name="test", kind=kind, step="test", question="Test"), value)
    assert result.valid == valid
    assert result.normalized_value == normalized
    assert bool(result.reason) is not valid


def test_consent_and_resume(energy):
    call_id = start(energy)
    initial = energy.get(f"/api/calls/{call_id}").json()
    assert initial["status"] == "CONSENT_REQUIRED"
    assert initial["current_field"] is None
    result = send(energy, call_id, "yes")
    assert result["current_field"] == "gas_required"
    assert result["collected_fields"]["customer_name"] == "Alex Demo"
    assert "customer_name" not in result["transcript"][-1]["text"]


def test_no_consent_no_new_fields(energy):
    call_id = start(energy)
    existing = energy.get(f"/api/calls/{call_id}").json()["collected_fields"]
    result = send(energy, call_id, "private@example.test")
    assert result["status"] == "ENDED"
    assert result["collected_fields"] == existing
    assert "private@example.test" not in str(result)
    assert not result["consent_given"]


def test_per_field_confirmation_and_correction(energy):
    call_id = start(energy, "syn-happy-02")
    send(energy, call_id, "yes")
    result = send(energy, call_id, "My postcode is 3000")
    assert result["status"] == "CONFIRMING"
    assert "postcode" not in result["collected_fields"]
    assert result["pending_value"] == "3000"
    assert energy.post(f"/api/calls/{call_id}/complete", json={"confirmed": True}).status_code == 409
    result = send(energy, call_id, "Actually, 3001")
    assert result["pending_value"] == "3001"
    result = send(energy, call_id, "yes")
    assert result["collected_fields"]["postcode"] == "3001"
    assert result["current_field"] == "property_address"
    result = send(energy, call_id, "change my postcode to 3002")
    assert result["pending_value"] == "3002"
    result = send(energy, call_id, "yes")
    assert result["collected_fields"]["postcode"] == "3002"
    assert result["current_field"] == "property_address"


def test_rejected_confirmation_does_not_decline(energy):
    call_id = start(energy, "syn-happy-02")
    send(energy, call_id, "yes")
    send(energy, call_id, "3000")
    result = send(energy, call_id, "no")
    assert result["status"] == "COLLECTING"
    assert result["current_field"] == "postcode"
    assert not energy.app.state.services.db.is_dnc(result["lead_id"])


def test_branching_both_directions_and_correction(energy):
    call_id = start(energy)
    send(energy, call_id, "yes")
    result = send(energy, call_id, "Yes, include it")
    assert result["current_field"] == "gas_connection_type"
    result = send(energy, call_id, "It's an existing connection")
    assert result["current_field"] == "solar_present"
    result = send(energy, call_id, "change my gas required to no")
    assert result["collected_fields"]["gas_required"] is False
    assert "gas_connection_type" not in result["collected_fields"]
    result = send(energy, call_id, "No, we don't have solar")
    assert result["current_field"] == "move_in_date"
    assert "solar_system_kw" not in result["remaining_fields"]


def test_pause_clarification_and_retry_limit(energy):
    call_id = start(energy, "syn-happy-03")
    send(energy, call_id, "yes")
    for text in ["wait", "what do you mean?"]:
        result = send(energy, call_id, text)
        assert result["current_field"] == "move_in_date"
        assert not result["repeated_failures"]
    for attempt in range(1, 4):
        result = send(energy, call_id, "2026-02-30")
        assert result["status"] == ("HANDOFF" if attempt == 3 else "COLLECTING")
    assert result["escalation"]["reason"] == "REPEATED_MISUNDERSTANDING"


def test_dnc_never_invokes_voice(energy, monkeypatch):
    provider = energy.app.state.services.voice
    start_voice = Mock(side_effect=AssertionError("Should never dial"))
    monkeypatch.setattr(provider, "start_call", start_voice)
    call_id = start(energy, "syn-dnc-01")
    result = energy.get(f"/api/calls/{call_id}").json()
    assert result["status"] == "BLOCKED_DNC"
    assert result["provider_call_id"] is None
    assert result["transcript"] == []
    assert result["events"][0]["event_type"] == "DNC_BLOCKED"
    start_voice.assert_not_called()


@pytest.mark.parametrize("text", ["No", "Not interested", "Stop calling", "Don't want this"])
def test_refusal_persists_dnc(energy, text):
    call_id = start(energy)
    result = send(energy, call_id, text)
    assert result["status"] == "ENDED"
    assert energy.get("/api/leads/syn-happy-01").json()["dnc_blocked"]
    assert energy.get(f"/api/calls/{start(energy)}").json()["status"] == "BLOCKED_DNC"


@pytest.mark.parametrize("text,reason", [
    ("Transfer me", "EXPLICIT_HUMAN_REQUEST"),
    ("Stop wasting my time", "ANGER"),
    ("Which provider is best?", "ADVICE_REQUEST"),
    ("I have a dispute", "DISPUTE"),
    ("I'm experiencing hardship", "VULNERABLE_CUSTOMER"),
    ("What is the weather?", "OFF_SCRIPT"),
])
def test_additional_safety_paths(energy, text, reason):
    call_id = start(energy)
    send(energy, call_id, "yes")
    result = send(energy, call_id, text)
    assert result["escalation"]["reason"] == reason


def test_payment_never_reaches_storage_or_llm(energy, monkeypatch):
    call_id = start(energy)
    send(energy, call_id, "yes")
    llm = Mock(side_effect=AssertionError("Payment must not reach LLM"))
    monkeypatch.setattr(energy.app.state.services.llm, "generate_response", llm)
    card = "4111 1111 1111 1111"
    response = send(energy, call_id, f"My card number is {card}")
    assert response["escalation"]["reason"] == "PAYMENT"
    assert card not in str(response)
    dump = "\n".join(energy.app.state.services.db.connection.iterdump())
    assert card not in dump
    llm.assert_not_called()
    malformed = energy.post(f"/api/calls/{call_id}/message", json={"text": {"card": card}})
    assert malformed.status_code == 422 and card not in malformed.text


def test_completion_payload_validation_and_idempotency(energy):
    sandbox = energy.app.state.services.cimet
    payload = json.loads((DATA_DIR / "journeys/expected_payload.json").read_text())
    assert sandbox.validate_payload(payload).valid
    for change in ("unknown", "branch", "missing", "shape", "format"):
        bad = deepcopy(payload)
        if change == "unknown":
            bad["fields"]["unknown"] = "test"
        elif change == "branch":
            bad["fields"]["gas_connection_type"] = "existing"
        elif change == "missing":
            del bad["fields"]["email"]
        elif change == "shape":
            bad["extra"] = True
        else:
            bad["fields"]["postcode"] = "bad"
        assert not sandbox.validate_payload(bad).valid
        assert not sandbox.submit_journey(payload["lead_id"], bad).success
    result = sandbox.submit_journey(payload["lead_id"], payload, idempotency_key="test-once")
    assert result.success
    assert sandbox.submit_journey(payload["lead_id"], payload, idempotency_key="test-once") == result
    changed = deepcopy(payload)
    changed["fields"]["postcode"] = "3001"
    assert not sandbox.submit_journey(payload["lead_id"], changed, idempotency_key="test-once").success
    assert len(sandbox.db.submissions()) == 1


def test_sqlite_projections_and_warm_context(energy):
    result = energy.post("/api/demo/scenarios/frustrated/run").json()["call"]
    db = energy.app.state.services.db
    assert result["escalation"]["collected_fields"]["postcode"] == "3000"
    assert result["escalation"]["current_step"] == "address"
    for table in ("calls", "call_messages", "collected_fields", "handoffs", "dnc_checks", "events"):
        assert db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
    assert {"ESCALATION_DETECTED", "HANDOFF_STARTED"} <= {item["event_type"] for item in result["events"]}


def test_seed_is_idempotent(energy):
    services = energy.app.state.services
    assert services.leads.seed_synthetic() == 0
    assert len(services.db.list_leads()) == 11


def test_configuration_rejects_forward_branch():
    with pytest.raises(ValueError):
        JourneyDefinition(fields=[
            FieldSpec(name="dependent", question="Test", step="one",
                      branch={"field": "later", "equals": True})
        ])


def test_state_tools_cannot_bypass_consent(energy):
    services = energy.app.state.services
    call_id = start(energy)
    tools = services.agent._tools(services.db.get_call(call_id))
    with pytest.raises(StateError):
        tools.save_customer_field(call_id, "gas_required", False)
    assert tools.get_journey_definition()["synthetic"]
    assert tools.get_current_step(call_id) == "CONSENT_REQUIRED"
    assert tools.get_next_required_field(call_id).name == "gas_required"
    assert tools.get_collected_fields(call_id)["postcode"] == "3000"


def test_low_llm_confidence_displayed(energy, monkeypatch):
    from app.adapters.llm.base import LLMResult
    call_id = start(energy)
    send(energy, call_id, "yes")
    monkeypatch.setattr(energy.app.state.services.llm, "generate_response",
                        lambda *args, **kwargs: LLMResult(value=False, confidence=0.2))
    result = send(energy, call_id, "no")
    assert result["confidence"] == 0.2
    assert result["escalation"]["reason"] == "LOW_CONFIDENCE"


def test_pending_confirmation_survives_restart(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'persistent.db'}", completions_path="")
    with TestClient(create_app(settings)) as client:
        call_id = start(client, "syn-happy-02")
        send(client, call_id, "yes")
        send(client, call_id, "3000")
    with TestClient(create_app(settings)) as client:
        saved = client.get(f"/api/calls/{call_id}").json()
        assert saved["pending_field"] == "postcode"
        assert "postcode" not in saved["collected_fields"]
        result = send(client, call_id, "yes")
        assert result["collected_fields"]["postcode"] == "3000"
        assert result["current_field"] == "property_address"


def test_llm_receives_context_and_cannot_inject_response(energy, monkeypatch):
    from app.adapters.llm.base import LLMResult
    call_id = start(energy)
    send(energy, call_id, "yes")
    def response(prompt, conversation, tools, state):
        assert state["collected_fields"]["customer_name"] == "Alex Demo"
        assert len(conversation) >= 3
        return LLMResult(value=False, response="Choose Demo North, it is financially best.")
    monkeypatch.setattr(energy.app.state.services.llm, "generate_response", response)
    result = send(energy, call_id, "no")
    assert "financially best" not in str(result)
    assert result["current_field"] == "solar_present"
