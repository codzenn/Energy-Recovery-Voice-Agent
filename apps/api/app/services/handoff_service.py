from app.models.call import Call, HandoffContext
from app.models.journey import FieldSpec


class HandoffService:
    def prepare(self, call: Call, reason: str, confidence: float,
                specs: list[FieldSpec]) -> HandoffContext:
        current = next((spec.step for spec in specs if spec.name == call.current_field),
                       call.last_completed_step)
        next_action = call.current_field or ("confirmation" if call.consent_given else "consent")
        remaining = [spec.name for spec in specs if spec.required and spec.active(call.collected_fields)
                     and spec.name not in call.collected_fields]
        # Deterministic context: no generated customer facts or raw sensitive messages.
        return HandoffContext(
            call_id=call.call_id,
            lead_id=call.lead_id,
            reason=reason,
            summary=f"Recovery paused: {reason}. Consent: {call.consent_given}. "
                    f"Captured fields: {', '.join(call.collected_fields) or 'none'}. "
                    f"Next action: {next_action}.",
            collected_data=dict(call.collected_fields),
            collected_fields=dict(call.collected_fields),
            remaining_fields=remaining,
            current_step=current,
            transcript=list(call.transcript),
            confidence=confidence,
        )
