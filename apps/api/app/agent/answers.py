import re


def boolean_answer(text: str) -> bool | None:
    """Conservative grounding for explicit yes/no expressions, independent of any LLM."""
    positive = bool(re.search(r"\b(yes|yeah|yep|true|we do|i do|include it)\b", text, re.I))
    negative = bool(re.search(r"\b(no|nope|false|don't|do not|none|without)\b",
                              text.replace("\u2019", "'"), re.I))
    return positive if positive != negative else None
