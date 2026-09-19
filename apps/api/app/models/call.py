from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.lead import utc_now


class CallStatus(StrEnum):
    IDLE = "IDLE"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    COLLECTING = "COLLECTING"
    CONFIRMING = "CONFIRMING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    HANDOFF = "HANDOFF"
    ENDED = "ENDED"
    BLOCKED_DNC = "BLOCKED_DNC"


class TranscriptEntry(BaseModel):
    role: Literal["agent", "customer", "system"]
    text: str
    created_at: datetime = Field(default_factory=utc_now)


class HandoffContext(BaseModel):
    handoff_id: str = Field(default_factory=lambda: str(uuid4()))
    call_id: str
    lead_id: str
    reason: str
    summary: str
    collected_data: dict[str, Any]
    current_step: str | None
    transcript: list[TranscriptEntry]
    confidence: float = Field(ge=0, le=1)
    collected_fields: dict[str, Any] = Field(default_factory=dict)
    remaining_fields: list[str] = Field(default_factory=list)


class AgentEvent(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    call_id: str
    lead_id: str
    event_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Call(BaseModel):
    call_id: str
    lead_id: str
    status: CallStatus = CallStatus.IDLE
    current_field: str | None = None
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    collected_fields: dict[str, Any] = Field(default_factory=dict)
    escalation: HandoffContext | None = None
    created_at: datetime = Field(default_factory=utc_now)
    last_completed_step: str | None = None
    consent_given: bool = False
    confirmed: bool = False
    repeated_failures: dict[str, int] = Field(default_factory=dict)
    complaint_count: int = 0
    end_reason: str | None = None
    completion_reference: str | None = None
    provider_call_id: str | None = None
    provider_error: str | None = None
    processed_event_ids: list[str] = Field(default_factory=list)
    pending_field: str | None = None
    pending_value: Any = None
    correction_field: str | None = None
    confidence: float = 1.0
    last_extraction: dict[str, Any] | None = None
    last_validation: dict[str, Any] | None = None
    completion_result: dict[str, Any] | None = None
    events: list[AgentEvent] = Field(default_factory=list)
    remaining_fields: list[str] = Field(default_factory=list)
