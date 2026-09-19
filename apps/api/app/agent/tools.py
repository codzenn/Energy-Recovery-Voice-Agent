from typing import Any

from app.agent.escalation import EscalationReason
from app.agent.state import ConversationState, StateError
from app.db.database import Database
from app.models.call import HandoffContext
from app.models.journey import FieldSpec, JourneyResult, ValidationResult
from app.models.lead import Lead
from app.services.handoff_service import HandoffService
from app.services.journey_service import JourneyService
from app.services.lead_service import BaseDNCProvider


class AgentTools:
    """Call-bound tools; adapters never get unchecked write access."""

    def __init__(self, db: Database, state: ConversationState, journey: JourneyService,
                 handoff: HandoffService, dnc: BaseDNCProvider):
        self.db, self.state = db, state
        self.journey, self.handoff, self.dnc = journey, handoff, dnc

    def _check_lead(self, lead_id: str) -> None:
        if lead_id not in {self.state.call.lead_id, self.state.call.call_id}:
            raise StateError("Tool lead does not match the active call")

    def get_lead(self, lead_id: str) -> Lead:
        self._check_lead(lead_id)
        return self.journey.client.get_lead(lead_id)

    def get_next_field(self, lead_id: str) -> FieldSpec | None:
        self._check_lead(lead_id)
        # TODO/TOMORROW-CIMET-INTEGRATION: map branching/ordering from supplied journey.
        return self.state.get_next_required_field()

    def save_customer_field(self, lead_id: str, field: str, value: Any) -> ValidationResult:
        self._check_lead(lead_id)
        result = self.state.save_field(field, value)
        lead = self.db.get_lead(self.state.call.lead_id)
        self.state.call.last_validation = result.model_dump()
        if result.valid and not self.state.call.pending_field:
            # TODO/TOMORROW-CIMET-INTEGRATION: map remote progress writes here.
            lead.fields = dict(self.state.call.collected_fields)
            lead.last_completed_step = self.state.call.last_completed_step
            lead.status = "in_progress"
            lead.missing_fields = list(self.state.call.remaining_fields)
        self.db.save_session(self.state.call, lead)
        return result

    def confirm_answer(self) -> ValidationResult:
        result = self.state.confirm_answer()
        lead = self.db.get_lead(self.state.call.lead_id)
        lead.fields = dict(self.state.call.collected_fields)
        lead.last_completed_step = self.state.call.last_completed_step
        lead.missing_fields = list(self.state.call.remaining_fields)
        lead.status = "in_progress"
        self.db.save_session(self.state.call, lead)
        return result

    def get_journey_definition(self, journey_id: str = "energy-demo") -> dict:
        if journey_id != "energy-demo":
            raise StateError("Unknown journey")
        return {"journey_id": journey_id, "synthetic": True,
                "fields": [spec.model_dump() for spec in self.state.specs]}

    def get_current_step(self, call_id: str) -> str | None:
        self._check_lead(call_id)
        spec = self.state.get_current_field()
        return spec.step if spec else self.state.call.status.value

    def get_next_required_field(self, call_id: str) -> FieldSpec | None:
        self._check_lead(call_id)
        return self.state.get_next_required_field()

    def get_collected_fields(self, call_id: str) -> dict[str, Any]:
        self._check_lead(call_id)
        return dict(self.state.call.collected_fields)

    def validate_customer_field(self, field: str, value: Any) -> ValidationResult:
        # TODO/TOMORROW-CIMET-INTEGRATION: add supplied field validation here.
        return self.state.validate_field(field, value)

    def complete_journey(self, lead_id: str) -> JourneyResult:
        self._check_lead(lead_id)
        self.state.complete_journey()
        self.db.save_session(self.state.call)
        lead = self.db.get_lead(self.state.call.lead_id)
        lead.fields = dict(self.state.call.collected_fields)
        result = self.journey.complete_journey(lead, self.state.call.call_id)
        self.state.call.completion_result = result.model_dump()
        if result.success and result.reference:
            self.state.mark_completed(result.reference)
            lead.status = "completed"
        self.db.save_session(self.state.call, lead)
        return result

    def request_handoff(self, call_id: str, reason: EscalationReason, confidence: float = 1.0) -> HandoffContext:
        self._check_lead(call_id)
        context = self.handoff.prepare(self.state.call, reason.value, confidence, self.state.specs)
        self.state.prepare_handoff(context)
        self.db.save_session(self.state.call)
        return context

    def end_call(self, call_id: str, reason: str | None = None) -> None:
        # Preserve the original bound-call shorthand used internally.
        if reason is None:
            reason = call_id
        else:
            self._check_lead(call_id)
        self.state.end_call(reason)
        self.db.save_session(self.state.call)

    def check_dnc(self, lead_id: str) -> bool:
        self._check_lead(lead_id)
        return self.dnc.check_dnc(lead_id)
