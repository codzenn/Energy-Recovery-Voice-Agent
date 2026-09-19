"""Browser voice lifecycle adapter.

The web client owns microphone capture and speech synthesis. The audio route uses
local Whisper before invoking the agent. This adapter keeps the agent independent
of browser transport details.
"""

from app.adapters.voice.base import BaseVoiceProvider
from app.models.call import HandoffContext
from app.models.lead import Lead


class BrowserVoiceProvider(BaseVoiceProvider):
    name = "browser"

    def start_call(self, lead: Lead, call_id: str) -> str:
        return f"browser-{call_id}"

    def speak(self, provider_call_id: str, text: str) -> None:
        # SpeechSynthesis runs in the customer's browser; the agent transcript is
        # the handoff-safe source of truth for the text to speak.
        return None

    def listen(self, provider_call_id: str) -> str | None:
        # /api/voice/{call_id}/audio transcribes and submits finalized turns.
        return None

    def end_call(self, provider_call_id: str) -> None:
        return None

    def transfer_call(self, provider_call_id: str, context: HandoffContext) -> None:
        # The browser displays the persisted handoff context for a human operator.
        return None
