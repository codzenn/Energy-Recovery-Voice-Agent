import pytest

from app.agent.escalation import evaluate_message
from app.tests.conftest import send


@pytest.mark.parametrize(("text", "reason"), [
    ("I want to speak to a person.", "EXPLICIT_HUMAN_REQUEST"),
    ("I am furious, this is ridiculous", "ANGER"),
    ("I've already told you this three times.", "REPEATED_COMPLAINT"),
    ("I want to pay by card.", "PAYMENT"),
    ("4111 1111 1111 1111", "PAYMENT"),
    ("Which plan do you recommend?", "ADVICE_REQUEST"),
    ("What is the weather today?", "OFF_SCRIPT"),
    ("I dispute this bill", "DISPUTE"),
    ("I'm experiencing financial hardship", "VULNERABLE_CUSTOMER"),
])
def test_escalation_rules(text, reason):
    result = evaluate_message(text)
    assert result.should_handoff
    assert result.reason == reason


def test_thresholds():
    assert evaluate_message("ordinary", confidence=0.2).reason == "LOW_CONFIDENCE"
    assert evaluate_message("", repeated_failures=2).reason == "REPEATED_MISUNDERSTANDING"
    assert evaluate_message("ordinary", sensitive_context=True).reason == "VULNERABLE_CUSTOMER"
    assert not evaluate_message("ordinary answer").should_handoff


@pytest.mark.parametrize("message", [
    "I want to speak to a person.", "I want to pay by card.", "I am furious",
    "I've already told you this three times.", "What plan should I choose?",
])
def test_handoff_in_api_before_consent(client, call, message):
    result = send(client, call["call_id"], message)
    assert result["status"] == "HANDOFF"
    assert not result["consent_given"]
    assert result["collected_fields"] == {}


def test_payment_not_persisted(client, call):
    send(client, call["call_id"], "yes")
    result = send(client, call["call_id"], "My card is 4111 1111 1111 1111")
    assert result["escalation"]["reason"] == "PAYMENT"
    assert "4111" not in str(result)
    assert "4111" not in client.get(f"/api/calls/{call['call_id']}").text


def test_low_confidence_affirmative_consent_is_recorded(client, call):
    result = send(client, call["call_id"], "yes", confidence=0.2)
    assert result["consent_given"]
    assert result["status"] == "COLLECTING"
    assert result["transcript"][1]["text"] == "[Consent given]"


def test_repeated_misunderstanding(client, call):
    call_id = call["call_id"]
    send(client, call_id, "yes")
    send(client, call_id, "demo text")
    first = send(client, call_id, "not a number")
    assert first["status"] == "COLLECTING"
    second = send(client, call_id, "still not a number")
    assert second["escalation"]["reason"] == "REPEATED_MISUNDERSTANDING"


def test_handoff_preserves_context(client, call):
    call_id = call["call_id"]
    send(client, call_id, "yes")
    send(client, call_id, "captured once")
    result = send(client, call_id, "a human please")
    context = result["escalation"]
    assert context["collected_data"] == {"field_1": "captured once"}
    assert context["current_step"] == "demo_step_4"
    assert context["call_id"] == call_id
    assert context["transcript"] == result["transcript"]


def test_repeated_complaints_across_turns(client, call):
    call_id = call["call_id"]
    send(client, call_id, "yes")
    send(client, call_id, "I have a complaint")
    result = send(client, call_id, "You are not listening")
    assert result["escalation"]["reason"] == "REPEATED_COMPLAINT"
    assert result["collected_fields"] == {}


@pytest.mark.parametrize("text,sensitive", [
    ("private circumstances", True),
    ("I need a human because of domestic violence", False),
])
def test_sensitive_content_redacted_regardless_of_reason(client, call, text, sensitive):
    send(client, call["call_id"], "yes")
    result = send(client, call["call_id"], text, sensitive_context=sensitive)
    assert result["status"] == "HANDOFF"
    assert text not in str(result)
    assert result["collected_fields"] == {}
