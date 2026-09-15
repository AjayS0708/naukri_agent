from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes.health import router as health_router
from backend.api.routes.profile import router as profile_router
from backend.api.routes.ai import router as ai_router
from backend.core.config import get_settings
from backend.core.exceptions import ApplicationError
from backend.core.logging import configure_logging, get_logger
from backend.database.database import initialize_database
import backend.models  # noqa: F401 - registers SQLAlchemy metadata before startup

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    logger.info("application_started", extra={"component": "application"})
    yield
    logger.info("application_stopped", extra={"component": "application"})


app = FastAPI(title=settings.app_name, version=settings.app_version, docs_url="/api/docs" if settings.is_development else None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.exception_handler(ApplicationError)
async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
    logger.warning("application_error", extra={"component": "api", "error_category": exc.category.value})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "category": exc.category.value})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Request validation failed.", "category": "VALIDATION_ERROR"})


app.include_router(health_router, prefix="/api")
app.include_router(profile_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
