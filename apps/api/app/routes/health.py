from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    services = request.app.state.services
    return {
        "status": "ok", "test_data_only": True,
        "providers": {"llm": services.llm.name, "voice": services.voice.name,
                      "cimet": "synthetic" if services.synthetic_mode else "mock", "dnc": services.settings.dnc_provider},
        "warnings": services.warnings,
    }


@router.get("/api/journey/fields")
def fields(request: Request):
    services = request.app.state.services
    return {"demo_only": not bool(services.settings.field_schema_path),
            "fields": services.specs}


@router.get("/api/journeys/energy-demo")
def journey(request: Request):
    return request.app.state.services.definition
