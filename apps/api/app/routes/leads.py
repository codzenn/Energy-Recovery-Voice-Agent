from fastapi import APIRouter, Request

from app.models.lead import Lead

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("", response_model=list[Lead])
def list_leads(request: Request):
    services = request.app.state.services
    leads = services.db.list_leads()
    for lead in leads:
        lead.dnc_blocked = lead.dnc_blocked or services.db.is_dnc(lead.lead_id)
    return leads


@router.get("/{lead_id}", response_model=Lead)
def get_lead(lead_id: str, request: Request):
    services = request.app.state.services
    lead = services.cimet.get_lead(lead_id)
    lead.dnc_blocked = lead.dnc_blocked or services.db.is_dnc(lead_id)
    return lead


@router.post("", response_model=Lead, status_code=201)
def create_lead(lead: Lead, request: Request):
    return request.app.state.services.leads.create(lead)
