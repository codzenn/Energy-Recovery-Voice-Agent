from app.adapters.voice.base import BaseVoiceProvider
from app.models.call import HandoffContext
from app.models.lead import Lead


class MockVoiceProvider(BaseVoiceProvider):
    """No phone, microphone, recording, ASR, or live transfer is performed."""

    name = "mock"

    def start_call(self, lead: Lead, call_id: str) -> str:
        return f"mock-{call_id}"

    def speak(self, provider_call_id: str, text: str) -> None:
        pass  # Agent transcript is the local output.

    def listen(self, provider_call_id: str) -> str | None:
        return None  # Local CLI/API supplies final text events.

    def end_call(self, provider_call_id: str) -> None:
        pass

    def transfer_call(self, provider_call_id: str, context: HandoffContext) -> None:
        pass  # The persisted HandoffContext represents the mock transfer.
