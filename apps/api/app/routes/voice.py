import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.models.call import Call

router = APIRouter(prefix="/api/voice", tags=["voice"])
TERMINAL = {"COMPLETED", "HANDOFF", "ENDED", "BLOCKED_DNC"}
MAX_AUDIO_BYTES = 3_000_000


@router.get("/capabilities")
def capabilities(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        request.app.state.services.speech.prepare()
    except Exception:
        raise HTTPException(503, "Local speech model unavailable. Run python -m app.prepare_speech.")
    return {"transcription": "local-whisper", "ready": True, "recording": "browser-memory"}


class AudioResult(BaseModel):
    call: Call
    heard: bool


@router.post("/{call_id}/audio", response_model=AudioResult)
async def audio_message(call_id: str, event_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    services = request.app.state.services
    call = services.db.get_call(call_id)
    if call.status in TERMINAL:
        raise HTTPException(409, "Call is not accepting speech")
    if str(event_id) in call.processed_event_ids:
        return AudioResult(call=call, heard=True)
    if request.headers.get("content-type", "").split(";")[0] != "audio/wav":
        raise HTTPException(415, "Send mono PCM16 audio/wav")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio turn is too large")
    try:
        text, confidence = await run_in_threadpool(services.speech.transcribe, bytes(data))
    except ValueError:
        raise HTTPException(422, "Invalid or overlong audio turn")
    except Exception:
        raise HTTPException(503, "Transcription failed. Check the local speech model.")
    finally:
        data.clear()
    # No raw transcript is returned: the agent applies consent/payment redaction.
    if not text:
        return AudioResult(call=services.db.get_call(call_id), heard=False)
    call = await run_in_threadpool(
        services.agent.message, call_id, text, confidence, event_id=str(event_id),
    )
    return AudioResult(call=call, heard=True)


class VoiceEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    call_id: str = Field(min_length=1)
    type: Literal["transcript.final", "call.ended"]
    text: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def require_text(self):
        if self.type == "transcript.final" and not (self.text and self.text.strip()):
            raise ValueError("Final transcript requires nonempty text")
        return self


@router.post("/webhook", response_model=Call)
def webhook(event: VoiceEvent, request: Request, x_voice_webhook_secret: str = Header(default="")):
    services = request.app.state.services
    expected = services.settings.voice_webhook_secret
    if expected and not secrets.compare_digest(expected, x_voice_webhook_secret):
        raise HTTPException(401, "Invalid webhook secret")
    if services.voice.name != "mock" and not expected:
        raise HTTPException(503, "Configure webhook authentication before enabling real voice")
    # TODO/TOMORROW-CIMET-INTEGRATION: verify provider-native signatures and map events.
    if event.type == "call.ended":
        return services.agent.end_call(event.call_id)
    return services.agent.message(event.call_id, event.text, event.confidence, event_id=event.event_id)
