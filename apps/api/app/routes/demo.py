from fastapi import APIRouter, Request
from app.services.scenario_service import ScenarioService, scenarios

router = APIRouter(prefix="/api/demo", tags=["synthetic-demo"])


@router.get("/scenarios")
def list_scenarios():
    return [{key: item[key] for key in ("scenario", "title", "lead_id", "expected_status", "expected_reason")}
            for item in scenarios()]


@router.post("/scenarios/{scenario}/run")
def run_scenario(scenario: str, request: Request):
    return ScenarioService(request.app.state.services).run(scenario)
