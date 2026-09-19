import pytest

from app.agent.state import ConversationState, StateError
from app.models.call import CallStatus
from app.models.journey import FieldSpec, load_field_specs
from app.models.lead import Lead
from app.tests.conftest import send


def test_state_transitions_and_consent():
    state = ConversationState.start_call(Lead(lead_id="test"), load_field_specs())
    assert state.call.status == CallStatus.CONSENT_REQUIRED
    with pytest.raises(StateError):
        state.save_field("field_1", "value")
    state.record_consent(True)
    assert state.call.status == CallStatus.COLLECTING
    assert state.call.current_field == "field_1"
    assert state.save_field("field_1", "value").valid
    assert state.call.current_field == "field_2"
    assert not state.save_field("field_2", "bad").valid
    assert "field_2" not in state.call.collected_fields
    state.save_field("field_2", "4")
    state.save_field("field_3", "alpha")
    assert state.call.status == CallStatus.CONFIRMING
    with pytest.raises(StateError):
        state.complete_journey()
    state.complete_journey(confirmed=True)
    assert state.call.status == CallStatus.COMPLETING
    state.mark_completed("mock-reference")
    assert state.call.status == CallStatus.COMPLETED
    with pytest.raises(StateError):
        state.save_field("field_1", "changed")


def test_dynamic_fields_and_no_reasking():
    specs = [
        FieldSpec(name="custom_a", step="a", question="A?"),
        FieldSpec(name="custom_b", step="b", question="B?", kind="boolean"),
    ]
    state = ConversationState.start_call(
        Lead(lead_id="custom", fields={"custom_a": "already known"}, last_completed_step="a"), specs)
    state.record_consent(True)
    assert state.call.current_field == "custom_b"
    assert state.save_field("custom_b", "yes").valid
    assert state.call.collected_fields["custom_a"] == "already known"
    assert state.call.status == CallStatus.CONFIRMING


def test_preconsent_data_omitted(client, call):
    result = send(client, call["call_id"], "private@example.test")
    assert result["status"] == "ENDED"
    assert result["collected_fields"] == {}
    assert "private@example.test" not in str(result)


@pytest.mark.parametrize("message", ["No", "I'm not interested.", "Stop calling me"])
def test_decline_and_dnc(client, call, message):
    result = send(client, call["call_id"], message)
    assert result["status"] == "ENDED"
    assert client.post("/api/calls/start", json={"lead_id": call["lead_id"]}).json()["status"] == "BLOCKED_DNC"
    assert client.post(f"/api/calls/{call['call_id']}/message", json={"text": "yes"}).status_code == 409


def test_repeated_start_is_idempotent(client, call):
    again = client.post("/api/calls/start", json={"lead_id": call["lead_id"]}).json()
    assert again["call_id"] == call["call_id"]


def test_unknown_and_out_of_order_fields():
    state = ConversationState.start_call(Lead(lead_id="test"), load_field_specs())
    assert not state.validate_field("unknown", "x").valid
    state.record_consent(True)
    with pytest.raises(StateError):
        state.save_field("field_3", "alpha")


@pytest.mark.parametrize("kind,choices", [("boolean", []), ("choice", ["yes", "no"])])
def test_no_is_a_valid_field_answer(client, services, call, kind, choices):
    services.specs[:] = [FieldSpec(name="demo_flag", step="demo", question="Demo flag?",
                                  kind=kind, choices=choices)]
    send(client, call["call_id"], "yes")
    result = send(client, call["call_id"], "no")
    assert result["status"] == "CONFIRMING"
    assert result["collected_fields"]["demo_flag"] == (False if kind == "boolean" else "no")
    assert not services.db.is_dnc(call["lead_id"])


def test_noncollectable_field_hands_off(client, services, call):
    services.specs[0].voice_collectable = False
    result = send(client, call["call_id"], "yes")
    assert result["status"] == "HANDOFF"
    assert result["collected_fields"] == {}
