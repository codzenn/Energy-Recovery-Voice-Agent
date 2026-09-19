import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError

from app.agent.state import StateError
from app.config import Settings
from app.container import Container
from app.routes import calls, demo, health, leads, voice


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.services = Container(settings)
        yield
        application.state.services.db.close()

    application = FastAPI(title="Synthetic Energy Demo API", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware, allow_origins=[settings.web_origin],
        # Next may select 3001+ when 3000 is occupied. Keep the local hackathon
        # dashboard usable on either localhost spelling without opening CORS to
        # non-local origins.
        allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1):\d+",
        allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Voice-Webhook-Secret"],
    )

    @application.exception_handler(KeyError)
    async def not_found(request: Request, error: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(error.args[0])})

    @application.exception_handler(StateError)
    async def invalid_state(request: Request, error: StateError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        # Pydantic's default response echoes invalid input, which may contain card data.
        return JSONResponse(status_code=422, content={"detail": "Invalid request shape or value"})

    @application.exception_handler(sqlite3.IntegrityError)
    async def conflict(request: Request, error: sqlite3.IntegrityError):
        return JSONResponse(status_code=409, content={"detail": "Lead already exists or reference is invalid"})

    for router in (health.router, leads.router, calls.router, voice.router, demo.router):
        application.include_router(router)

    @application.get("/", include_in_schema=False)
    def api_home():
        """Small local landing page for the synthetic demo."""
        return {
            "service": "Synthetic Energy Demo API",
            "synthetic_demo": True,
            "dashboard": settings.web_origin,
            "documentation": "/docs",
            "health": "/health",
        }

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)
    return application


app = create_app()
