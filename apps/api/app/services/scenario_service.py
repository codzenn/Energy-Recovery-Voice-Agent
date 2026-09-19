import json
from uuid import uuid4

from app.agent.state import TERMINAL_STATES
from app.models.journey import DATA_DIR
from app.models.lead import Lead


def scenarios() -> list[dict]:
    items = [json.loads(path.read_text()) for path in sorted((DATA_DIR / "transcripts").glob("*.json"))]
    items.append({"synthetic": True, "scenario": "dnc", "title": "DNC Block",
                  "lead_id": "syn-dnc-01", "expected_status": "BLOCKED_DNC",
                  "expected_reason": None, "turns": []})
    return items


class ScenarioService:
    def __init__(self, services):
        self.services = services

    def run(self, scenario: str) -> dict:
        fixture = next((item for item in scenarios() if item["scenario"] == scenario), None)
        if fixture is None:
            raise KeyError("Unknown demo scenario")
        # Fresh fixture clone makes repeat runs independent of persisted opt-outs/completions.
        row = next(item for item in json.loads((DATA_DIR / "leads.json").read_text())
                   if item["lead_id"] == fixture["lead_id"])
        lead = Lead(lead_id=f"{row['lead_id']}-{uuid4().hex[:8]}", fields=row["prefilled_fields"],
                    customer_name=row["customer_name"], phone=row["phone"], email=row["email"],
                    last_completed_step=row["last_completed_step"], scenario=scenario,
                    dnc_blocked=scenario == "dnc")
        self.services.leads.create(lead)
        call = self.services.agent.start_call(lead.lead_id)
        trace = [{"stage": "CALL STARTED" if call.status != "BLOCKED_DNC" else "DNC BLOCKED",
                  "call": call.model_dump(mode="json")}]
        for index, turn in enumerate(fixture["turns"]):
            if turn["speaker"] != "customer":
                continue  # Agent output must come from the real engine, never the fixture.
            if call.status in TERMINAL_STATES:
                break
            call = self.services.agent.message(
                call.call_id, turn["text"], confidence=turn.get("confidence", 1.0),
                event_id=f"{call.call_id}:{index}",
            )
            trace.append({"stage": "CUSTOMER RESPONSE", "call": call.model_dump(mode="json")})
        reason = call.escalation.reason if call.escalation else None
        passed = call.status == fixture["expected_status"] and reason == fixture["expected_reason"]
        if scenario == "happy_path" and passed:
            expected = json.loads((DATA_DIR / "journeys/expected_payload.json").read_text())
            passed = call.collected_fields == expected["fields"] and bool(call.completion_reference)
        return {"scenario": scenario, "synthetic": True, "passed": passed,
                "expected_status": fixture["expected_status"], "expected_reason": fixture["expected_reason"],
                "call": call, "trace": trace}
