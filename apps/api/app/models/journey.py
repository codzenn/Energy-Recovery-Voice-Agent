import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, model_validator

DATA_DIR = Path(__file__).resolve().parents[4] / "data"


class BranchRule(BaseModel):
    field: str
    equals: str | int | bool


class FieldSpec(BaseModel):
    name: str = Field(min_length=1)
    question: str = Field(min_length=1)
    step: str
    kind: Literal["text", "integer", "choice", "boolean", "email", "postcode", "date", "phone"] = "text"
    required: bool = True
    choices: list[str] = Field(default_factory=list)
    pattern: str | None = None
    min_length: int = 1
    max_length: int = 200
    minimum: int | None = None
    maximum: int | None = None
    voice_collectable: bool = True
    clarification: str = "Please repeat the answer."
    confirmation: str = "I heard {value}. Is that correct?"
    confirm_required: bool = False
    retry_limit: int = Field(default=2, ge=2, le=3)
    branch: BranchRule | None = None

    @model_validator(mode="before")
    @classmethod
    def configuration_names(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "type" in value:
                kind = value.pop("type")
                value["kind"] = "choice" if kind == "enum" else kind
            if "script" in value:
                value["question"] = value.pop("script")
            rules = value.pop("validation", {})
            value.update(rules)
        return value

    def active(self, fields: dict[str, Any]) -> bool:
        return self.branch is None or (
            self.branch.field in fields
            and type(fields[self.branch.field]) is type(self.branch.equals)
            and fields[self.branch.field] == self.branch.equals
        )

    @model_validator(mode="after")
    def check_rules(self) -> "FieldSpec":
        if self.kind == "choice" and not self.choices:
            raise ValueError("Choice fields need choices")
        if self.pattern:
            re.compile(self.pattern)
        if self.max_length < self.min_length or self.min_length < 0:
            raise ValueError("Invalid length bounds")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Invalid numeric bounds")
        return self


class ValidationResult(BaseModel):
    valid: bool
    value: Any = None
    error: str | None = None

    @computed_field
    @property
    def normalized_value(self) -> Any:
        return self.value if self.valid else None

    @computed_field
    @property
    def reason(self) -> str | None:
        return self.error


class JourneyResult(BaseModel):
    success: bool
    reference: str | None = None
    error: str | None = None
    mock: bool = True
    journey_id: str = "energy-demo"
    submission_id: str | None = None
    status: str | None = None


class JourneyDefinition(BaseModel):
    journey_id: str = "energy-demo"
    version: str = "1"
    synthetic: Literal[True] = True
    description: str = "Synthetic demo only, not production CIMET data."
    fields: list[FieldSpec]

    @model_validator(mode="after")
    def check_order(self):
        seen = set()
        for spec in self.fields:
            if spec.name in seen or (spec.branch and spec.branch.field not in seen):
                raise ValueError("Fields must be unique; branch dependencies must precede their fields")
            seen.add(spec.name)
        if not seen:
            raise ValueError("Journey requires fields")
        return self


def load_journey(path: str = "") -> JourneyDefinition:
    return JourneyDefinition.model_validate(json.loads(
        Path(path or DATA_DIR / "journeys/energy_demo.json").read_text()))


def load_field_specs(path: str = "") -> list[FieldSpec]:
    if path and path != "legacy":
        data = json.loads(Path(path).read_text())
        specs = [FieldSpec.model_validate(item) for item in (data["fields"] if isinstance(data, dict) else data)]
    else:
        # TODO/TOMORROW-CIMET-INTEGRATION: synthetic fields, NOT Energy schema.
        specs = [
            FieldSpec(name="field_1", step="demo_step_3",
                      question="What is the value for demo field one?"),
            FieldSpec(name="field_2", step="demo_step_4", kind="integer", minimum=0,
                      question="What whole number should I use for demo field two?"),
            FieldSpec(name="field_3", step="demo_step_5", kind="choice",
                      choices=["alpha", "beta"],
                      question="For demo field three, would you like alpha or beta?"),
        ]
    if not specs or len({spec.name for spec in specs}) != len(specs):
        raise ValueError("Field schema must be nonempty and contain unique names")
    return specs
