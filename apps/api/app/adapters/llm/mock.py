from typing import Any
import re

from app.adapters.llm.base import BaseLLMProvider, LLMResult
from app.agent.answers import boolean_answer


class MockLLMProvider(BaseLLMProvider):
    name = "mock"

    def generate_response(self, system_prompt: str, conversation: list[dict[str, str]],
                          tools: list[dict[str, Any]], state: dict[str, Any]) -> LLMResult:
        text = conversation[-1]["content"].strip()
        kind = state["field"]["kind"]
        # Deterministic conversational extraction, not business validation.
        text = re.sub(r"^(?:um|uh|well|okay|actually|sorry)[, .]+\s*", "", text, flags=re.I)
        text = re.split(r"\b(?:actually|sorry,? I mean|no,? I mean)\b", text, flags=re.I)[-1].strip(" ,.")
        if text.lower().strip(".!?") in {
            "i don't know", "i do not know", "unsure", "huh", "what", "not sure", "unknown",
        }:
            return LLMResult(understood=False)
        if kind == "boolean":
            value = boolean_answer(text)
            if value is None:
                return LLMResult(understood=False)
            return LLMResult(value=value, evidence=text)
        if kind == "choice":
            choices = state["field"].get("choices", [])
            found = [choice for choice in choices if re.search(r"\b" + re.escape(choice) + r"\b", text, re.I)]
            if len(found) == 1:
                return LLMResult(value=found[0], evidence=found[0], response="Thanks.")
            return LLMResult(value=text, evidence=text, understood=len(found) < 2)
        patterns = {
            "postcode": r"\b\d{4}\b", "date": r"\b\d{4}-\d{2}-\d{2}\b",
            "integer": r"(?<!\w)-?\d+(?!\w)",
            "email": r"[\w.+-]+(?:@| at )[\w.-]+(?:(?: dot )[\w-]+)*",
            "phone": r"\b04\d{8}\b",
        }
        if kind in patterns:
            found = re.findall(patterns[kind], text, re.I)
            if len(found) == 1:
                return LLMResult(value=found[0], evidence=found[0], response="Thanks.")
            if len(found) > 1:
                return LLMResult(understood=False)
        text = re.sub(r"^(?:my name is|it is|it's|the address is|my email is)\s+", "", text, flags=re.I)
        return LLMResult(value=text, evidence=text, confidence=1.0, response="Thanks.")
