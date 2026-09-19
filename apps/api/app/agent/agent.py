import re

from app.adapters.llm.base import BaseLLMProvider, LLMResult
from app.adapters.voice.base import BaseVoiceProvider
from app.agent.answers import boolean_answer
from app.agent.escalation import (
    EscalationReason, detect_payment, evaluate_message, is_affirmative, is_complaint,
    is_decline, safe_transcript_text,
)
from app.agent.prompts import DISCLOSURE
from app.agent.state import ConversationState, StateError, TERMINAL_STATES
from app.agent.tools import AgentTools
from app.db.database import Database
from app.models.call import Call, CallStatus, TranscriptEntry
from app.models.journey import FieldSpec
from app.services.handoff_service import HandoffService
from app.services.journey_service import JourneyService
from app.services.lead_service import BaseDNCProvider


class RecoveryAgent:
    def __init__(self, db: Database, specs: list[FieldSpec], llm: BaseLLMProvider,
                 voice: BaseVoiceProvider, journey: JourneyService,
                 handoff: HandoffService, dnc: BaseDNCProvider, prompt: str):
        self.db, self.specs, self.llm, self.voice = db, specs, llm, voice
        self.journey, self.handoff, self.dnc, self.prompt = journey, handoff, dnc, prompt

    def _tools(self, call: Call) -> AgentTools:
        return AgentTools(self.db, ConversationState(call, self.specs),
                          self.journey, self.handoff, self.dnc)

    def extract_answer(self, call: Call, spec: FieldSpec, text: str) -> LLMResult:
        return self.llm.generate_response(
            self.prompt,
            [{"role": "assistant" if entry.role == "agent" else "user", "content": entry.text}
             for entry in call.transcript[-12:-1] if entry.role != "system"]
            + [{"role": "user", "content": text}],
            tools=[], state={"field": spec.model_dump(), "collected_fields": call.collected_fields},
        )

    def _say(self, call: Call, text: str) -> None:
        call.transcript.append(TranscriptEntry(role="agent", text=text))
        self.db.save_session(call)
        try:
            self.voice.speak(call.provider_call_id or call.call_id, text)
        except Exception:
            call.provider_error = "Voice output failed; transport requires attention."
            if call.status not in TERMINAL_STATES:
                self._tools(call).end_call("VOICE_PROVIDER_FAILURE")
                self._transport_end(call)
            self.db.save_session(call)

    def _transport_end(self, call: Call) -> None:
        try:
            self.voice.end_call(call.provider_call_id or call.call_id)
        except Exception:
            call.provider_error = "Voice disconnect failed; transport requires attention."
        self.db.save_session(call)

    def start_call(self, lead_id: str) -> Call:
        with self.db.lock:
            lead = self.journey.client.get_lead(lead_id)
            try:
                blocked = self.dnc.check_dnc(lead_id)
            except Exception:
                blocked = True
                self.db.record_dnc(lead_id, True)
            if blocked:
                call = ConversationState.start_call(lead, self.specs).call
                call.status = CallStatus.BLOCKED_DNC
                call.end_reason = "DNC_GATE"
                self.db.save_session(call)
                return call
            if lead.status == "completed":
                raise StateError("This lead's journey is already completed; use a new synthetic lead")
            existing = self.db.active_call(lead_id)
            if existing:
                return existing
            state = ConversationState.start_call(lead, self.specs)
            call = state.call
            self.db.save_session(call)
            try:
                call.provider_call_id = self.voice.start_call(lead, call.call_id)
            except Exception:
                call.provider_error = "Voice call could not start."
                state.end_call("VOICE_PROVIDER_FAILURE")
                self.db.save_session(call)
                return call
            self._say(call, DISCLOSURE)
            return call

    def _ask_next(self, call: Call, acknowledgement: str | None = None) -> None:
        # Only harmless acknowledgements may be generated; configured questions own the script.
        prefix = acknowledgement + " " if acknowledgement in {"Thanks.", "Thank you.", "Got it."} else ""
        if call.pending_field:
            spec = next(item for item in self.specs if item.name == call.pending_field)
            self._say(call, prefix + spec.confirmation.format(value=call.pending_value))
            return
        spec = self._tools(call).get_next_field(call.lead_id)
        if spec:
            if not spec.voice_collectable:
                self._handoff(call, EscalationReason.OFF_SCRIPT)
            else:
                self._say(call, prefix + spec.question)
        else:
            # Only already validated values are read back.
            summary = "; ".join(f"{key}: {value}" for key, value in call.collected_fields.items())
            self._say(call, f"I have {summary or 'all required information'}. "
                      "Is that correct, and may I complete the journey?")

    def _handoff(self, call: Call, reason: EscalationReason, confidence: float = 1.0) -> Call:
        tools = self._tools(call)
        context = tools.request_handoff(call.call_id, reason, confidence)
        self._say(call, "I'll pass this to a human with the information already captured. "
                  "This local demo prepares the handoff; it does not connect a live person."
                  if self.voice.name == "mock" else
                  "I'll pass this to a human with the information already captured.")
        context.transcript = list(call.transcript)
        try:
            self.voice.transfer_call(call.provider_call_id or call.call_id, context)
        except Exception:
            call.provider_error = "Human transfer failed; saved context needs manual follow-up."
        self.db.save_session(call)
        return call

    def request_handoff(self, call_id: str, reason: EscalationReason) -> Call:
        with self.db.lock:
            call = self.db.get_call(call_id)
            if call.status == CallStatus.HANDOFF:
                return call
            if call.status in TERMINAL_STATES:
                raise StateError("Call has already ended")
            return self._handoff(call, reason)

    def end_call(self, call_id: str, reason: str = "PROVIDER_ENDED") -> Call:
        with self.db.lock:
            call = self.db.get_call(call_id)
            if call.status not in TERMINAL_STATES:
                self._tools(call).end_call(reason)
                self._transport_end(call)
            return call

    def complete_journey(self, call_id: str, confirmed: bool = False) -> Call:
        with self.db.lock:
            call = self.db.get_call(call_id)
            if call.status == CallStatus.COMPLETED:
                return call
            tools = self._tools(call)
            tools.state.complete_journey(confirmed)
            if confirmed:
                call.transcript.append(TranscriptEntry(role="system", text="Explicit completion confirmation received."))
            self.db.save_session(call)
            try:
                result = tools.complete_journey(call.lead_id)
            except Exception:
                call.provider_error = "Journey submission unavailable; retry with the same call ID."
                self._say(call, "Your progress is saved, but completion is not confirmed yet.")
                return call
            if result.success and call.status == CallStatus.COMPLETED:
                call.provider_error = None
                self._say(call, "Thanks, your demo journey is complete." if result.mock
                          else "Thanks, your journey is complete.")
                self._transport_end(call)
            else:
                call.provider_error = "Journey submission was not accepted; review or retry."
                self._say(call, "Your progress is saved, but completion is not confirmed yet.")
            return call

    def message(self, call_id: str, text: str, confidence: float = 1.0,
                sensitive_context: bool = False, event_id: str | None = None) -> Call:
        with self.db.lock:
            call = self.db.get_call(call_id)
            if event_id and event_id in call.processed_event_ids:
                return call
            if call.status in TERMINAL_STATES:
                raise StateError("Call has already ended")
            if event_id:
                call.processed_event_ids.append(event_id)
            call.transcript.append(TranscriptEntry(
                role="customer", text=safe_transcript_text(text, call.consent_given, sensitive_context)))
            call.confidence = confidence
            call.last_extraction = call.last_validation = None
            self.db.save_session(call)
            tools = self._tools(call)
            spec = tools.get_next_field(call.lead_id)
            # A bare "no" can answer a boolean/choice field, not revoke consent.
            field_negative = (
                call.status == CallStatus.COLLECTING and spec is not None
                and (spec.kind == "boolean" or (spec.kind == "choice" and "no" in
                     {choice.casefold() for choice in spec.choices}))
                and text.strip().lower().rstrip(".!") == "no"
            )
            pending_negative = bool(call.pending_field and text.strip().lower().rstrip(".!") == "no")
            if is_decline(text) and not field_negative and not pending_negative:
                # Local suppression persists across restarts and future attempts.
                self.db.block_contact(call.lead_id)
                tools.end_call("CUSTOMER_DECLINED")
                self._say(call, "Thank you for your time. We won't continue. Goodbye.")
                self._transport_end(call)
                return call
            if call.status == CallStatus.CONSENT_REQUIRED and is_affirmative(text):
                tools.state.record_consent(True)
                self._ask_next(call)
                return call
            call.complaint_count += int(is_complaint(text))
            clarification = bool(re.fullmatch(
                r"\s*(?:please repeat|repeat that|what do you mean|can you repeat that|"
                r"what does that mean|could you explain that)[?.!]*\s*", text, re.I))
            pause = bool(re.fullmatch(r"\s*(?:wait|hang on|one moment|give me a moment)[,.!]*\s*", text, re.I))
            decision = evaluate_message("" if clarification or pause else text, confidence, sensitive_context=sensitive_context,
                                        complaint_count=call.complaint_count)
            if decision.should_handoff:
                return self._handoff(call, decision.reason, decision.confidence)
            if pause:
                self._say(call, "Of course. Take your time; your progress is saved.")
                return call
            if clarification:
                current = tools.state.get_current_field()
                self._say(call, current.clarification if current else
                          ("This is a recorded synthetic Energy recovery call. Do you consent to continue?"
                           if not call.consent_given else "Please confirm the captured details to submit the synthetic journey."))
                return call
            if call.status == CallStatus.CONSENT_REQUIRED:
                tools.end_call("CONSENT_NOT_GIVEN")
                self._say(call, "I don't have your consent, so I won't collect any information. Goodbye.")
                self._transport_end(call)
                return call
            # Explicit corrections target only named configured fields, never inferred facts.
            correction = re.fullmatch(r"(?:please )?change (?:my |the )?(.+?) to (.+)", text.strip(), re.I)
            if correction:
                label, answer = correction.groups()
                target = next((item for item in self.specs if label.lower().replace(" ", "_") == item.name), None)
                if target is None:
                    return self._handoff(call, EscalationReason.OFF_SCRIPT)
                tools.state.correct_answer(target.name)
                text = answer
            if call.status == CallStatus.CONFIRMING:
                if call.pending_field:
                    if is_affirmative(text):
                        tools.confirm_answer()
                        self._ask_next(call)
                        return call
                    field = call.pending_field
                    tools.state.correct_answer(field)
                    if pending_negative:
                        self._ask_next(call)
                        return call
                    # "Actually, ..." re-enters extraction for this pending field.
                else:
                    if is_affirmative(text):
                        self.db.save_session(call)
                        return self.complete_journey(call.call_id, confirmed=True)
                    self._failed_attempt(call, "__confirmation__",
                                         "Please confirm, or say change my field name to the corrected value.")
                    return call
            if call.status == CallStatus.COMPLETING:
                self._say(call, "Your progress is saved. Completion is pending; the operator can retry or arrange a handoff.")
                return call
            spec = tools.get_next_field(call.lead_id)
            if spec is None:
                raise StateError("No current field")
            if is_complaint(text):
                self._failed_attempt(call, spec.name, "I'm sorry. " + spec.question)
                return call
            try:
                result = self.extract_answer(call, spec, text)
            except Exception:
                return self._handoff(call, EscalationReason.LOW_CONFIDENCE, 0.0)
            call.confidence = min(confidence, result.confidence)
            decision = evaluate_message("", call.confidence)
            if decision.should_handoff:
                return self._handoff(call, decision.reason, decision.confidence)
            if result.handoff_required:
                return self._handoff(call, EscalationReason.OFF_SCRIPT)
            if result.intent in {"pause", "clarify"}:
                self._say(call, "Take your time." if result.intent == "pause" else spec.clarification)
                return call
            if not result.understood or result.value is None:
                self._failed_attempt(call, spec.name, "I couldn't capture that. " + spec.question)
                return call
            # Reject inferred values. Extracted facts must be grounded in this utterance.
            grounded = str(result.value).casefold() in text.casefold()
            if isinstance(result.value, bool):
                grounded = boolean_answer(text) is result.value
            if not grounded:
                return self._handoff(call, EscalationReason.LOW_CONFIDENCE, 0.0)
            # Only grounded, non-sensitive extracted values become observable.
            if detect_payment(str(result.value)):
                return self._handoff(call, EscalationReason.PAYMENT)
            call.last_extraction = {"field": spec.name, "value": result.value, "confidence": call.confidence}
            if not tools.validate_customer_field(spec.name, result.value).valid:
                validation = tools.save_customer_field(call.lead_id, spec.name, result.value)
                self._check_failures(call, spec.name, (validation.error or "Invalid answer.") + " " + spec.clarification)
            else:
                tools.save_customer_field(call.lead_id, spec.name, result.value)
                self._ask_next(call, result.response)
            return call

    def _failed_attempt(self, call: Call, field: str, retry: str) -> None:
        call.last_validation = {"valid": False, "normalized_value": None, "reason": "Answer could not be understood"}
        call.repeated_failures[field] = call.repeated_failures.get(field, 0) + 1
        self._check_failures(call, field, retry)

    def _check_failures(self, call: Call, field: str, retry: str) -> None:
        spec = next((item for item in self.specs if item.name == field), None)
        failures = call.repeated_failures.get(field, 0)
        limit = spec.retry_limit if spec else 2
        decision = evaluate_message("", repeated_failures=2 if failures >= limit else 0)
        if decision.should_handoff:
            self._handoff(call, decision.reason, decision.confidence)
        else:
            self._say(call, retry)
