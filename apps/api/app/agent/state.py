import re
from datetime import date
from typing import Any
from uuid import uuid4

from app.agent.escalation import detect_payment
from app.models.call import Call, CallStatus, HandoffContext
from app.models.journey import FieldSpec, ValidationResult
from app.models.lead import Lead

TERMINAL_STATES = {CallStatus.COMPLETED, CallStatus.HANDOFF, CallStatus.ENDED, CallStatus.BLOCKED_DNC}


class StateError(ValueError):
    pass


def validate_field(spec: FieldSpec, value: Any) -> ValidationResult:
    if not spec.voice_collectable or detect_payment(str(value)):
        return ValidationResult(valid=False, error="This information cannot be collected by voice.")
    if spec.kind == "integer":
        if isinstance(value, bool) or not re.fullmatch(r"-?\d+", str(value).strip()):
            return ValidationResult(valid=False, error="Please provide a whole number.")
        parsed = int(str(value).strip())
        if ((spec.minimum is not None and parsed < spec.minimum)
                or (spec.maximum is not None and parsed > spec.maximum)):
            return ValidationResult(valid=False, error="That number is outside the allowed range.")
        return ValidationResult(valid=True, value=parsed)
    if spec.kind == "boolean":
        if isinstance(value, bool):
            return ValidationResult(valid=True, value=value)
        normalized = str(value).strip().lower()
        if normalized not in {"yes", "no", "true", "false"}:
            return ValidationResult(valid=False, error="Please answer yes or no.")
        return ValidationResult(valid=True, value=normalized in {"yes", "true"})
    if not isinstance(value, str):
        return ValidationResult(valid=False, error="Please provide a text answer.")
    value = value.strip()
    if spec.kind == "email":
        value = re.sub(r"\s+at\s+", "@", value, flags=re.I)
        value = re.sub(r"\s+dot\s+", ".", value, flags=re.I).lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            return ValidationResult(valid=False, error="Please provide a valid email address.")
    if spec.kind == "postcode" and not re.fullmatch(r"\d{4}", value):
        return ValidationResult(valid=False, error="Please provide a four-digit Australian postcode.")
    if spec.kind == "phone" and not re.fullmatch(r"04\d{8}", value):
        return ValidationResult(valid=False, error="Please provide a synthetic Australian-style mobile number.")
    if spec.kind == "date":
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError()
            date.fromisoformat(value)
        except ValueError:
            return ValidationResult(valid=False, error="Please provide a valid calendar date as YYYY-MM-DD.")
    if not spec.min_length <= len(value) <= spec.max_length:
        return ValidationResult(valid=False, error=f"Please use {spec.min_length} to {spec.max_length} characters.")
    if spec.pattern and not re.fullmatch(spec.pattern, value):
        return ValidationResult(valid=False, error="That answer does not match the required format.")
    if spec.kind == "choice":
        choice = next((item for item in spec.choices if item.casefold() == value.casefold()), None)
        if choice is None:
            return ValidationResult(valid=False, error=f"Please choose: {', '.join(spec.choices)}.")
        value = choice
    return ValidationResult(valid=True, value=value)


class ConversationState:
    """Provider-independent, explicitly guarded state transitions."""

    def __init__(self, call: Call, specs: list[FieldSpec]):
        self.call = call
        self.specs = specs

    @classmethod
    def start_call(cls, lead: Lead, specs: list[FieldSpec]) -> "ConversationState":
        return cls(Call(call_id=str(uuid4()), lead_id=lead.lead_id,
                        status=CallStatus.CONSENT_REQUIRED,
                        last_completed_step=lead.last_completed_step,
                        collected_fields=dict(lead.fields)), specs)

    def get_next_required_field(self) -> FieldSpec | None:
        if self.call.correction_field:
            return next(spec for spec in self.specs if spec.name == self.call.correction_field)
        return next((spec for spec in self.specs
                     if spec.required and spec.active(self.call.collected_fields)
                     and spec.name not in self.call.collected_fields), None)

    def get_current_field(self) -> FieldSpec | None:
        name = self.call.pending_field or self.call.current_field
        return next((spec for spec in self.specs if spec.name == name), None)

    def request_consent(self) -> None:
        if self.call.status not in {CallStatus.IDLE, CallStatus.CONSENT_REQUIRED}:
            raise StateError("Consent cannot be requested in this state")
        self.call.status = CallStatus.CONSENT_REQUIRED

    def record_consent(self, consent: bool) -> None:
        if self.call.status != CallStatus.CONSENT_REQUIRED:
            raise StateError("Consent is only accepted at the disclosure step")
        if not consent:
            self.end_call("CONSENT_DECLINED")
            return
        self.call.consent_given = True
        self.move_to_next_field()

    def move_to_next_field(self) -> None:
        if not self.call.consent_given or self.call.status in TERMINAL_STATES:
            raise StateError("An active consented call is required")
        spec = self.get_next_required_field()
        self.call.remaining_fields = [
            item.name for item in self.specs if item.required and item.active(self.call.collected_fields)
            and item.name not in self.call.collected_fields
        ]
        self.call.current_field = spec.name if spec else None
        self.call.status = CallStatus.COLLECTING if spec else CallStatus.CONFIRMING

    def validate_field(self, field: str, value: Any) -> ValidationResult:
        spec = next((spec for spec in self.specs if spec.name == field), None)
        if spec is None:
            return ValidationResult(valid=False, error="Unknown journey field")
        return validate_field(spec, value)

    def save_field(self, field: str, value: Any, confirmed: bool = False) -> ValidationResult:
        if not self.call.consent_given or self.call.status != CallStatus.COLLECTING:
            raise StateError("Information cannot be collected before consent or outside collection")
        if field != self.call.current_field:
            raise StateError("Only the current missing field can be saved")
        result = self.validate_field(field, value)
        if result.valid:
            spec = next(spec for spec in self.specs if spec.name == field)
            if spec.confirm_required and not confirmed:
                self.call.pending_field = field
                self.call.pending_value = result.value
                self.call.status = CallStatus.CONFIRMING
                return result
            self.call.collected_fields[field] = result.value
            self.call.pending_field = None
            self.call.pending_value = None
            self.call.correction_field = None
            self.call.confirmed = False
            # Configuration order ensures dependants are removed after a changed branch.
            for item in self.specs:
                if not item.active(self.call.collected_fields):
                    self.call.collected_fields.pop(item.name, None)
            if all(item.name in self.call.collected_fields for item in self.specs
                   if item.step == spec.step and item.required and item.active(self.call.collected_fields)):
                self.call.last_completed_step = spec.step
            self.call.repeated_failures.pop(field, None)
            self.move_to_next_field()
        else:
            self.call.repeated_failures[field] = self.call.repeated_failures.get(field, 0) + 1
        return result

    def confirm_answer(self) -> ValidationResult:
        if self.call.status != CallStatus.CONFIRMING or not self.call.pending_field:
            raise StateError("No pending answer to confirm")
        field, value = self.call.pending_field, self.call.pending_value
        self.call.status = CallStatus.COLLECTING
        self.call.current_field = field
        return self.save_field(field, value, confirmed=True)

    def correct_answer(self, field: str) -> None:
        if not self.call.consent_given or self.call.status not in {CallStatus.COLLECTING, CallStatus.CONFIRMING}:
            raise StateError("Corrections require an active consented call")
        spec = next((item for item in self.specs if item.name == field), None)
        if not spec or not spec.active(self.call.collected_fields):
            raise StateError("Cannot correct an inactive or unknown field")
        self.call.current_field = self.call.correction_field = field
        self.call.pending_field = None
        self.call.pending_value = None
        self.call.confirmed = False
        self.call.status = CallStatus.COLLECTING

    validate_answer = validate_field
    save_answer = save_field
    advance = move_to_next_field

    def complete_journey(self, confirmed: bool = False) -> None:
        if self.call.pending_field:
            raise StateError("Confirm the pending field before completing the journey")
        if self.call.status not in {CallStatus.CONFIRMING, CallStatus.COMPLETING}:
            raise StateError("All required fields must be collected before completion")
        if not self.call.consent_given or not (confirmed or self.call.confirmed):
            raise StateError("Explicit confirmation is required before submission")
        for spec in self.specs:
            if not spec.active(self.call.collected_fields):
                continue
            if spec.required and spec.name not in self.call.collected_fields:
                raise StateError(f"Missing field: {spec.name}")
            if spec.name in self.call.collected_fields:
                if not self.validate_field(spec.name, self.call.collected_fields[spec.name]).valid:
                    raise StateError(f"Invalid field: {spec.name}")
        self.call.confirmed = True
        self.call.status = CallStatus.COMPLETING

    def mark_completed(self, reference: str) -> None:
        if self.call.status != CallStatus.COMPLETING:
            raise StateError("Journey has not been submitted")
        self.call.completion_reference = reference
        self.call.status = CallStatus.COMPLETED

    def end_call(self, reason: str) -> None:
        if self.call.status in TERMINAL_STATES:
            raise StateError("Call has already ended")
        self.call.status = CallStatus.ENDED
        self.call.end_reason = reason

    def prepare_handoff(self, context: HandoffContext) -> None:
        if self.call.status in TERMINAL_STATES:
            raise StateError("Call has already ended")
        self.call.escalation = context
        self.call.status = CallStatus.HANDOFF
