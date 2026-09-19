from abc import ABC, abstractmethod

from app.models.call import HandoffContext
from app.models.lead import Lead


class BaseVoiceProvider(ABC):
    """TODO/TOMORROW-CIMET-INTEGRATION: provider maps transport to these operations.

    Normalize verified final speech events into /api/voice/webhook.
    Never send partial ASR transcripts to the agent.
    """

    name: str

    @abstractmethod
    def start_call(self, lead: Lead, call_id: str) -> str: ...

    @abstractmethod
    def speak(self, provider_call_id: str, text: str) -> None: ...

    @abstractmethod
    def listen(self, provider_call_id: str) -> str | None: ...

    @abstractmethod
    def end_call(self, provider_call_id: str) -> None: ...

    @abstractmethod
    def transfer_call(self, provider_call_id: str, context: HandoffContext) -> None: ...
