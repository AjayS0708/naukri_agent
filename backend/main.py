from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes.health import router as health_router
from backend.api.routes.profile import router as profile_router
from backend.api.routes.ai import router as ai_router
from backend.api.routes.matching import router as matching_router
from backend.api.routes.discovery import router as discovery_router
from backend.api.routes.application import router as application_router
from backend.api.routes.scheduler import router as scheduler_router, set_scheduler_service_instance
from backend.api.routes.ai_queue import router as ai_queue_router
from backend.api.routes.lifecycle import router as lifecycle_router, set_lifecycle_service_instance
from backend.api.routes.system import router as system_router, set_autostart_service_instance
from backend.api.routes.decision import router as decision_router
from backend.api.routes.feedback import router as feedback_router
from backend.api.routes.analytics import router as analytics_router
from backend.core.config import get_settings
from backend.core.exceptions import ApplicationError
from backend.core.logging import configure_logging, configure_production_logging, get_logger
from backend.database.database import initialize_database, SessionLocal
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import DiscoveryService
from backend.services.scheduler.service import SchedulerService
from backend.services.lifecycle import AgentLifecycleService
from backend.services.windows import WindowsAutoStartService
from backend.schemas.agent import AgentState
import backend.models  # noqa: F401 - registers SQLAlchemy metadata before startup

settings = get_settings()
# Use production-safe logging in production environment
if settings.is_production:
    configure_production_logging(settings.log_level)
else:
    configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()

    # Initialize shared services
    state_manager = AgentStateManager(initial_state=AgentState.IDLE)
    discovery_service = DiscoveryService(state_manager=state_manager)

    # Initialize scheduler service
    db = SessionLocal()
    try:
        scheduler_svc = SchedulerService(
            state_manager=state_manager,
            discovery_service=discovery_service
        )
        scheduler_svc.initialize(db)

        # Store in global for API routes
        set_scheduler_service_instance(scheduler_svc)

        # Initialize lifecycle service
        lifecycle_svc = AgentLifecycleService(
            state_manager=state_manager,
            scheduler_service=scheduler_svc
        )
        set_lifecycle_service_instance(lifecycle_svc)

        # Initialize auto-start service
        autostart_svc = WindowsAutoStartService()
        set_autostart_service_instance(autostart_svc)

        # Perform startup recovery
        recovery_result = lifecycle_svc.recover_on_startup(db)
        logger.info("startup_recovery_completed", extra={"recovery_stats": recovery_result.get("recovery_stats", {})})

        # NOTE: We do NOT auto-start the scheduler on startup
        # The scheduler should only start when the user explicitly starts the agent
        # This prevents automatic application submission after restart
        # Users can enable auto-start via Windows Task Scheduler, but the agent
        # will start in IDLE state and wait for explicit user action to begin processing

        db.close()
    except Exception as e:
        logger.error("service_initialization_failed", extra={"error": str(e)})
        db.close()

    logger.info("application_started", extra={"component": "application"})
    yield

    # Shutdown scheduler
    from backend.api.routes.scheduler import _scheduler_service_instance as routes_scheduler_instance
    if routes_scheduler_instance:
        try:
            await routes_scheduler_instance.shutdown()
        except Exception as e:
            logger.error("scheduler_shutdown_failed", extra={"error": str(e)})

    logger.info("application_stopped", extra={"component": "application"})


app = FastAPI(title=settings.app_name, version=settings.app_version, docs_url="/api/docs" if settings.is_development else None, redoc_url=None, lifespan=lifespan)

# CORS configuration - production-safe with configurable origins
# In development, allow all origins for convenience
# In production, use only configured origins
cors_origins = settings.cors_origins
if settings.is_development:
    # In development, allow localhost for convenience
    cors_origins = ["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:3000", "http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS", "DELETE"],
    allow_headers=["Content-Type", "X-Request-ID", "Authorization"],
)


@app.exception_handler(ApplicationError)
async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
    logger.warning("application_error", extra={"component": "api", "error_category": exc.category.value})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "category": exc.category.value})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Request validation failed.", "category": "VALIDATION_ERROR"})


@app.exception_handler(Exception)
async def generic_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler to prevent sensitive information exposure."""
    logger.error("unhandled_exception", extra={"component": "api", "error_type": type(exc).__name__})
    # In production, don't expose stack traces or sensitive details
    return JSONResponse(status_code=500, content={"detail": "An internal error occurred.", "category": "INTERNAL_ERROR"})


app.include_router(health_router, prefix="/api")
app.include_router(profile_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(matching_router)
app.include_router(discovery_router, prefix="/api")
app.include_router(application_router, prefix="/api/applications")
app.include_router(scheduler_router, prefix="/api")
app.include_router(ai_queue_router)
app.include_router(lifecycle_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(decision_router)
app.include_router(feedback_router)
app.include_router(analytics_router)
