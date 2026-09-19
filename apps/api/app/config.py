import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from app.models.journey import DATA_DIR

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass
class Settings:
    database_url: str = "sqlite:///./cimet.db"
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Browser speech recognition and speech synthesis are handled in the web client.
    # This adapter keeps the backend call lifecycle transport-neutral.
    voice_provider: str = "browser"
    dnc_provider: str = "mock"
    dnc_blocked_lead_ids: str = ""
    field_schema_path: str = ""
    system_prompt_path: str = ""
    web_origin: str = "http://localhost:3000"
    voice_webhook_secret: str = ""
    app_env: str = "development"
    completions_path: str = str(DATA_DIR / "completions.json")
    journey_path: str = ""
    speech_model: str = "base.en"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(**{
            name: os.getenv(name.upper(), field.default)
            for name, field in cls.__dataclass_fields__.items()
        })
