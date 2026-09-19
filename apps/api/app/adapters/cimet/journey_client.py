from abc import ABC, abstractmethod

from app.agent.state import validate_field
from app.db.database import Database
from app.models.journey import FieldSpec, JourneyResult, ValidationResult
from app.models.lead import Lead


class CimetJourneyClient(ABC):
    """TODO/TOMORROW-CIMET-INTEGRATION: map supplied schema/API here."""

    @abstractmethod
    def get_lead(self, lead_id: str) -> Lead: ...

    @abstractmethod
    def validate_payload(self, lead: Lead) -> ValidationResult: ...

    @abstractmethod
    def submit_journey(self, lead: Lead, idempotency_key: str) -> JourneyResult: ...


class MockCimetJourneyClient(CimetJourneyClient):
    def __init__(self, db: Database, specs: list[FieldSpec]):
        self.db = db
        self.specs = specs

    def get_lead(self, lead_id: str) -> Lead:
        return self.db.get_lead(lead_id)

    def validate_payload(self, lead: Lead) -> ValidationResult:
        for spec in self.specs:
            if spec.required and spec.name not in lead.fields:
                return ValidationResult(valid=False, error=f"Missing field: {spec.name}")
            if spec.name in lead.fields:
                result = validate_field(spec, lead.fields[spec.name])
                if not result.valid:
                    return result
        return ValidationResult(valid=True)

    def submit_journey(self, lead: Lead, idempotency_key: str) -> JourneyResult:
        result = self.validate_payload(lead)
        if not result.valid:
            return JourneyResult(success=False, error=result.error)
        return JourneyResult(success=True, reference=f"mock-{idempotency_key}")
