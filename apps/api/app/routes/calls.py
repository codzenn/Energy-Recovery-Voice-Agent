from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.agent.escalation import EscalationReason
from app.models.call import Call

router = APIRouter(prefix="/api/calls", tags=["calls"])


class StartRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=100)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    confidence: float = Field(default=1.0, ge=0, le=1)
    sensitive_context: bool = False
    event_id: str | None = Field(default=None, min_length=1, max_length=200)


class HandoffRequest(BaseModel):
    reason: EscalationReason = EscalationReason.EXPLICIT_HUMAN_REQUEST


class CompleteRequest(BaseModel):
    confirmed: bool = False


class EndRequest(BaseModel):
    reason: str = Field(default="CUSTOMER_STOPPED", min_length=1, max_length=100)


@router.post("/start", response_model=Call)
def start(body: StartRequest, request: Request):
    return request.app.state.services.agent.start_call(body.lead_id)


@router.get("/{call_id}", response_model=Call)
def get_call(call_id: str, request: Request):
    return request.app.state.services.db.get_call(call_id)


@router.post("/{call_id}/message", response_model=Call)
def message(call_id: str, body: MessageRequest, request: Request):
    return request.app.state.services.agent.message(call_id, **body.model_dump())


@router.post("/{call_id}/handoff", response_model=Call)
def handoff(call_id: str, body: HandoffRequest, request: Request):
    return request.app.state.services.agent.request_handoff(call_id, body.reason)


@router.post("/{call_id}/complete", response_model=Call)
def complete(call_id: str, body: CompleteRequest, request: Request):
    return request.app.state.services.agent.complete_journey(call_id, body.confirmed)


@router.post("/{call_id}/end", response_model=Call)
def end(call_id: str, body: EndRequest, request: Request):
    """End an active local browser conversation without adding the lead to DNC."""
    return request.app.state.services.agent.end_call(call_id, body.reason)
