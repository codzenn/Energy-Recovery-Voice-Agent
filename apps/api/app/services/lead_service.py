import json
from abc import ABC, abstractmethod

from app.agent.escalation import detect_payment
from app.agent.state import StateError, validate_field
from app.db.database import Database
from app.models.journey import DATA_DIR, FieldSpec
from app.models.lead import Lead


class BaseDNCProvider(ABC):
    @abstractmethod
    def check_dnc(self, lead_id: str) -> bool:
        """Return True if contact is prohibited; raise on unavailable checks."""


class MockDNCProvider(BaseDNCProvider):
    def __init__(self, db: Database, blocked_ids: str = "", configured_provider: str = "mock"):
        self.db = db
        self.blocked_ids = set(filter(None, (item.strip() for item in blocked_ids.split(","))))
        self.configured_provider = configured_provider

    def check_dnc(self, lead_id: str) -> bool:
        # TODO/TOMORROW-CIMET-INTEGRATION: replace with the supplied DNC gate.
        if self.configured_provider != "mock":
            raise StateError("Configured DNC provider is unavailable; call blocked")
        blocked = lead_id in self.blocked_ids or self.db.is_dnc(lead_id)
        self.db.record_dnc(lead_id, blocked)
        return blocked


class LeadService:
    def __init__(self, db: Database, specs: list[FieldSpec]):
        self.db = db
        self.specs = specs

    def create(self, lead: Lead) -> Lead:
        if detect_payment(json.dumps({"fields": lead.fields, "contact": lead.contact,
                                      "customer_name": lead.customer_name,
                                      "phone": lead.phone, "email": lead.email})):
            raise StateError("Payment data is prohibited, including in synthetic lead uploads")
        if lead.phone and not validate_field(
            FieldSpec(name="phone", question="Phone", step="contact", kind="phone"), lead.phone
        ).valid:
            raise StateError("Invalid synthetic phone format")
        for spec in self.specs:
            if spec.name in lead.fields:
                result = validate_field(spec, lead.fields[spec.name])
                if not result.valid:
                    raise StateError(f"Invalid existing value for {spec.name}: {result.error}")
                lead.fields[spec.name] = result.value
        lead.missing_fields = [spec.name for spec in self.specs if spec.required
                               and spec.active(lead.fields) and spec.name not in lead.fields]
        created = self.db.create_lead(lead)
        if lead.dnc_blocked:
            self.db.block_contact(lead.lead_id)
        return created

    def seed_synthetic(self) -> int:
        count = 0
        for row in json.loads((DATA_DIR / "leads.json").read_text()):
            try:
                self.db.get_lead(row["lead_id"])
                continue
            except KeyError:
                pass
            self.create(Lead(
                lead_id=row["lead_id"], customer_name=row["customer_name"],
                phone=row["phone"], email=row["email"], created_at=row["created_at"],
                status=row["lead_status"], fields=row["prefilled_fields"],
                last_completed_step=row["last_completed_step"], synthetic=row["synthetic"],
                contact={"phone": row["phone"], "email": row["email"]},
                dnc_blocked=row["lead_status"] == "blocked_dnc", scenario=row["scenario"],
            ))
            count += 1
        return count

    def seed_demo(self) -> None:
        try:
            self.db.get_lead("demo-energy-001")
        except KeyError:
            self.create(Lead(lead_id="demo-energy-001", last_completed_step="step_2"))
