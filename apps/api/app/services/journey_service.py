from app.adapters.cimet.journey_client import CimetJourneyClient
from app.models.journey import JourneyResult
from app.models.lead import Lead


class JourneyService:
    def __init__(self, client: CimetJourneyClient):
        self.client = client

    def complete_journey(self, lead: Lead, call_id: str) -> JourneyResult:
        validation = self.client.validate_payload(lead)
        if not validation.valid:
            return JourneyResult(success=False, error=validation.error)
        # A real adapter must send this stable key and reconcile ambiguous timeouts.
        return self.client.submit_journey(lead, idempotency_key=call_id)
