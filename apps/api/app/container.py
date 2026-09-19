from app.adapters.cimet.journey_client import MockCimetJourneyClient
from app.adapters.llm.mock import MockLLMProvider
from app.adapters.llm.openai import OpenAILLMProvider
from app.adapters.voice.browser import BrowserVoiceProvider
from app.adapters.voice.mock import MockVoiceProvider
from app.agent.agent import RecoveryAgent
from app.agent.prompts import load_system_prompt
from app.config import Settings
from app.db.database import Database
from app.models.journey import JourneyDefinition, load_field_specs, load_journey
from app.services.handoff_service import HandoffService
from app.services.journey_service import JourneyService
from app.services.lead_service import LeadService, MockDNCProvider
from app.services.synthetic_journey_service import SyntheticJourneyService
from app.services.speech_service import SpeechService


class Container:
    """Composition root: replace providers here, not in the conversation engine."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.speech = SpeechService(settings.speech_model)
        self.synthetic_mode = not settings.field_schema_path
        self.definition = (load_journey(settings.journey_path) if self.synthetic_mode else
                           JourneyDefinition(fields=load_field_specs(settings.field_schema_path)))
        self.specs = self.definition.fields
        self.db = Database(settings.database_url)
        self.warnings: list[str] = []
        self.llm = MockLLMProvider()
        if settings.llm_provider == "openai" and settings.openai_api_key:
            self.llm = OpenAILLMProvider(settings.openai_api_key, settings.openai_model)
        elif settings.llm_provider != "mock":
            self.warnings.append("Requested LLM unavailable; deterministic mock is active.")
        self.voice = MockVoiceProvider()
        if settings.voice_provider == "browser":
            self.voice = BrowserVoiceProvider()
        elif settings.voice_provider != "mock":
            self.warnings.append("Requested voice provider is not implemented; local mock is active. No phone call will be placed.")
        self.leads = LeadService(self.db, self.specs)
        if self.synthetic_mode:
            self.leads.seed_synthetic()
        else:
            self.leads.seed_demo()
        self.cimet = (SyntheticJourneyService(self.db, self.definition, settings.completions_path)
                      if self.synthetic_mode else MockCimetJourneyClient(self.db, self.specs))
        self.dnc = MockDNCProvider(self.db, settings.dnc_blocked_lead_ids, settings.dnc_provider)
        self.agent = RecoveryAgent(
            self.db, self.specs, self.llm, self.voice, JourneyService(self.cimet),
            HandoffService(), self.dnc, load_system_prompt(settings.system_prompt_path),
        )
