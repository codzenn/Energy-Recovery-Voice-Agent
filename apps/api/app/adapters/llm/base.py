from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMResult(BaseModel):
    value: str | int | bool | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    understood: bool = True
    handoff_required: bool = False
    intent: Literal["answer", "pause", "clarify", "correction", "unknown"] = "answer"
    evidence: str | None = None
    response: str | None = None


class BaseLLMProvider(ABC):
    name: str

    @abstractmethod
    def generate_response(
        self, system_prompt: str, conversation: list[dict[str, str]],
        tools: list[dict[str, Any]], state: dict[str, Any],
    ) -> LLMResult:
        """Extract the current answer only. The deterministic core owns all actions."""
