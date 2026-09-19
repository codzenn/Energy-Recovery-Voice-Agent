from app.models.journey import JourneyResult
from app.tests.conftest import send


def collect(client, call):
    for text in ["yes", "example", "12", "alpha"]:
        result = send(client, call["call_id"], text)
    assert result["status"] == "CONFIRMING"
    return result


def test_completion_and_idempotency(client, call):
    call_id = call["call_id"]
    assert client.post(f"/api/calls/{call_id}/complete", json={"confirmed": True}).status_code == 409
    collect(client, call)
    assert client.post(f"/api/calls/{call_id}/complete", json={}).status_code == 409
    result = send(client, call_id, "yes")
    assert result["status"] == "COMPLETED"
    assert result["completion_reference"] == f"mock-{call_id}"
    again = client.post(f"/api/calls/{call_id}/complete", json={}).json()
    assert again == result
    assert client.get("/api/leads/demo-energy-001").json()["status"] == "completed"


def test_rejected_journey_does_not_claim_success(client, services, call, monkeypatch):
    collect(client, call)
    monkeypatch.setattr(services.cimet, "submit_journey",
                        lambda *args, **kwargs: JourneyResult(success=False, error="Rejected"))
    result = send(client, call["call_id"], "yes")
    assert result["status"] == "COMPLETING"
    assert result["completion_reference"] is None
    assert client.get("/api/leads/demo-energy-001").json()["status"] != "completed"


def test_completion_outage_is_retryable(client, services, call, monkeypatch):
    collect(client, call)
    original = services.cimet.submit_journey
    def outage(*args, **kwargs):
        raise TimeoutError("unavailable")
    monkeypatch.setattr(services.cimet, "submit_journey", outage)
    result = send(client, call["call_id"], "yes")
    assert result["status"] == "COMPLETING"
    monkeypatch.setattr(services.cimet, "submit_journey", original)
    result = client.post(f"/api/calls/{call['call_id']}/complete", json={}).json()
    assert result["status"] == "COMPLETED"


def test_new_call_skips_saved_information(client, call):
    send(client, call["call_id"], "yes")
    send(client, call["call_id"], "saved once")
    client.post(f"/api/calls/{call['call_id']}/handoff", json={})
    next_call = client.post("/api/calls/start", json={"lead_id": call["lead_id"]}).json()
    result = send(client, next_call["call_id"], "yes")
    assert result["current_field"] == "field_2"
    assert result["collected_fields"] == {"field_1": "saved once"}
