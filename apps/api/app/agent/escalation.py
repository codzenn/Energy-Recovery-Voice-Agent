import re
from enum import StrEnum

from pydantic import BaseModel

MIN_CONFIDENCE = 0.65
MAX_FIELD_FAILURES = 2
MAX_COMPLAINTS = 2


class EscalationReason(StrEnum):
    EXPLICIT_HUMAN_REQUEST = "EXPLICIT_HUMAN_REQUEST"
    ANGER = "ANGER"
    REPEATED_COMPLAINT = "REPEATED_COMPLAINT"
    REPEATED_MISUNDERSTANDING = "REPEATED_MISUNDERSTANDING"
    OFF_SCRIPT = "OFF_SCRIPT"
    ADVICE_REQUEST = "ADVICE_REQUEST"
    PAYMENT = "PAYMENT"
    DISPUTE = "DISPUTE"
    VULNERABLE_CUSTOMER = "VULNERABLE_CUSTOMER"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class EscalationDecision(BaseModel):
    should_handoff: bool = False
    reason: EscalationReason | None = None
    confidence: float = 1.0


def matches(text: str, pattern: str) -> bool:
    return re.search(pattern, text.replace("\u2019", "'"), re.IGNORECASE) is not None


def detect_explicit_human_request(text: str) -> bool:
    return matches(text, r"\b(human|person|representative|operator|supervisor|real agent|someone real|transfer me)\b")


def detect_payment(text: str) -> bool:
    return matches(text, r"\b(card|payment|credit card|debit|cvv|cvc|iban|bsb|bank account|account number)\b"
                   r"|\bpay (by|with|using)\b|(?<!\d)(?:\d[ -]?){13,19}(?!\d)"
                   r"|\b(?:(?:zero|one|two|three|four|five|six|seven|eight|nine)[ ,.-]+){12,}"
                   r"(?:zero|one|two|three|four|five|six|seven|eight|nine)\b")


def detect_advice_request(text: str) -> bool:
    return matches(text, r"\b(advice|advise|recommend|recommendation|should i|best (plan|deal|provider)|"
                   r"which (energy )?(plan|provider|product)|what (plan|provider) should|financially better)\b")


def detect_anger_or_frustration(text: str) -> bool:
    return matches(text, r"\b(angry|furious|frustrat\w*|annoy\w*|ridiculous|useless|stupid|"
                   r"fed up|sick of|terrible|hate this|bloody|fuck\w*|stop wasting my time)\b")


def detect_off_script(text: str) -> bool:
    return "?" in text or matches(text, r"^\s*(why|how|what|who|when|where|can you|could you|tell me)\b")


def is_decline(text: str) -> bool:
    return matches(text, r"^\s*(no|nope|nah|no thanks|no thank you|stop)[.!]?\s*$"
                   r"|\b(not interested|don'?t (want to|wish to) (continue|proceed)|"
                   r"do not (want to )?continue|stop calling|do not call|don'?t call|"
                   r"remove me|end (the|this) call|leave me alone|stop the call|don'?t want this)\b")


def is_affirmative(text: str) -> bool:
    return matches(text, r"^\s*(yes|yes please|yes that'?s (right|correct)|yeah|yep|sure|"
                   r"okay|ok|i (agree|consent|confirm)|correct|go ahead|yes,? (go ahead|that's correct|that is correct))"
                   r"[.!]?\s*$")


def is_complaint(text: str) -> bool:
    return matches(text, r"\b(complain\w*|already told|told you|not listening|keep asking|again)\b")


def evaluate_message(
    text: str,
    confidence: float = 1.0,
    repeated_failures: int = 0,
    conversation_state: dict | None = None,
    sensitive_context: bool = False,
    complaint_count: int = 0,
) -> EscalationDecision:
    if conversation_state:
        complaint_count = conversation_state.get("complaint_count", complaint_count)
        sensitive_context = conversation_state.get("sensitive_context", sensitive_context)
    reason = None
    if detect_explicit_human_request(text):
        reason = EscalationReason.EXPLICIT_HUMAN_REQUEST
    elif detect_payment(text):
        reason = EscalationReason.PAYMENT
    elif sensitive_context or matches(text, r"\b(vulnerable|suicid\w*|self.harm|domestic (abuse|violence)|"
                                             r"hardship|can'?t afford|cannot afford|medical emergency|"
                                             r"bereave\w*|dementia)\b"):
        reason = EscalationReason.VULNERABLE_CUSTOMER
    elif matches(text, r"\b(dispute|fraud|unauthori[sz]ed|overcharg\w*|scam)\b"):
        reason = EscalationReason.DISPUTE
    elif (is_complaint(text) and matches(text, r"\b(three times|twice|repeatedly|already|again)\b")) or complaint_count >= MAX_COMPLAINTS:
        reason = EscalationReason.REPEATED_COMPLAINT
    elif detect_anger_or_frustration(text):
        reason = EscalationReason.ANGER
    elif detect_advice_request(text):
        reason = EscalationReason.ADVICE_REQUEST
    elif detect_off_script(text):
        reason = EscalationReason.OFF_SCRIPT
    elif repeated_failures >= MAX_FIELD_FAILURES:
        reason = EscalationReason.REPEATED_MISUNDERSTANDING
    elif confidence < MIN_CONFIDENCE:
        reason = EscalationReason.LOW_CONFIDENCE
    return EscalationDecision(should_handoff=reason is not None, reason=reason,
                              confidence=confidence if reason == EscalationReason.LOW_CONFIDENCE else 0.98)


def should_handoff(**kwargs: object) -> bool:
    return evaluate_message(**kwargs).should_handoff


def safe_transcript_text(text: str, consent_given: bool, sensitive_context: bool = False) -> str:
    decision = evaluate_message(text)
    sensitive_words = matches(text, r"\b(vulnerable|suicid\w*|self.harm|domestic (abuse|violence)|"
                              r"hardship|can'?t afford|cannot afford|medical emergency|"
                              r"bereave\w*|dementia|dispute|fraud|unauthori[sz]ed|overcharg\w*|scam)\b")
    if sensitive_context or sensitive_words or detect_payment(text) or decision.reason in {
        EscalationReason.VULNERABLE_CUSTOMER, EscalationReason.DISPUTE,
    }:
        return "[Sensitive content omitted]"
    if not consent_given:
        if is_affirmative(text):
            return "[Consent given]"
        if is_decline(text):
            return "[Consent declined]"
        return "[Pre-consent content omitted]"
    return text
