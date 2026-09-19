import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError
from typing import Any, Literal

from app.agent.state import validate_field
from app.db.database import Database
from app.models.journey import JourneyDefinition, JourneyResult, ValidationResult
from app.models.lead import Lead


class SyntheticPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    journey_id: Literal["energy-demo"]
    lead_id: str
    synthetic: Literal[True]
    fields: dict[str, Any]


class SyntheticJourneyService:
    """Local completion sandbox; no CIMET endpoint or production schema is implied."""

    def __init__(self, db: Database, definition: JourneyDefinition, completions_path: str):
        self.db, self.definition = db, definition
        self.completions_path = Path(completions_path) if completions_path else None

    def get_lead(self, lead_id: str) -> Lead:
        return self.db.get_lead(lead_id)

    def payload_for(self, lead: Lead) -> dict:
        return {"journey_id": self.definition.journey_id, "lead_id": lead.lead_id,
                "synthetic": True, "fields": dict(lead.fields)}

    def validate_payload(self, payload: dict | Lead) -> ValidationResult:
        if isinstance(payload, Lead):
            payload = self.payload_for(payload)
        try:
            body = SyntheticPayload.model_validate(payload)
        except ValidationError:
            return ValidationResult(valid=False, error="Invalid synthetic submission shape")
        specs = self.definition.fields
        if set(body.fields) - {spec.name for spec in specs}:
            return ValidationResult(valid=False, error="Unknown journey fields")
        for spec in specs:
            present = spec.name in body.fields
            active = spec.active(body.fields)
            if present and not active:
                return ValidationResult(valid=False, error=f"Inactive branch field: {spec.name}")
            if active and spec.required and not present:
                return ValidationResult(valid=False, error=f"Missing field: {spec.name}")
            if present:
                result = validate_field(spec, body.fields[spec.name])
                if not result.valid:
                    return ValidationResult(valid=False, error=f"{spec.name}: {result.error}")
                if type(result.value) is not type(body.fields[spec.name]) or result.value != body.fields[spec.name]:
                    return ValidationResult(valid=False, error=f"Field must be normalized: {spec.name}")
        return ValidationResult(valid=True, value=body.model_dump())

    def submit_journey(self, lead_id: str | Lead, payload: dict | None = None,
                       idempotency_key: str | None = None) -> JourneyResult:
        if isinstance(lead_id, Lead):
            lead = lead_id
            lead_id, payload = lead.lead_id, self.payload_for(lead)
        validation = self.validate_payload(payload or {})
        if not validation.valid or payload.get("lead_id") != lead_id:
            return JourneyResult(success=False, error=validation.error or "Lead mismatch")
        try:
            self.db.get_lead(lead_id)
        except KeyError:
            return JourneyResult(success=False, error="Unknown lead")
        submission_id = f"synthetic-{idempotency_key or lead_id}"
        with self.db.lock:
            existing = self.db.get_submission(submission_id)
            if existing:
                if self.db.submission_payload(submission_id) != payload:
                    return JourneyResult(success=False, error="Submission key already used for another payload")
                self.export_completions()
                return JourneyResult.model_validate(existing)
            result = JourneyResult(success=True, reference=submission_id, submission_id=submission_id,
                                   status="COMPLETED", journey_id=self.definition.journey_id)
            self.db.save_submission(submission_id, lead_id, payload, result.model_dump())
            self.export_completions()
            return result

    def export_completions(self) -> None:
        if self.completions_path is None:
            return
        self.completions_path.parent.mkdir(parents=True, exist_ok=True)
        # SQLite is authoritative; atomically refresh the human-readable local export.
        with tempfile.NamedTemporaryFile(mode="w", dir=self.completions_path.parent, delete=False) as output:
            json.dump(self.db.submissions(), output, indent=2)
            temporary = output.name
        os.replace(temporary, self.completions_path)
