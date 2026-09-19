from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Lead(BaseModel):
    lead_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    status: str = "dropped_off"
    last_completed_step: str | None = None
    contact: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    test_data: Literal[True] = True
    synthetic: Literal[True] = True
    customer_name: str = ""
    phone: str = ""
    email: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    dnc_blocked: bool = False
    scenario: str | None = None
