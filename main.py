"""
LeadFlow AI — Enterprise Cold Email Outreach & Intelligence Platform.
Main Application Entrypoint.
Initializes FastAPI, validates production readiness, mounts middleware and routes.
"""

import logging
import sys
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import shutil
# Metrics counters
_api_requests_total = 0
_api_errors_total = 0

from core.config import settings, AppEnvironment
from database.database import init_db
from api.routes import router as api_router

# ── Logging Setup ────────────────────────────────────────────────────────────

def setup_logging():
    """Configure structured logging to console and rotating log file."""
    log_format = "%(asctime)s │ %(levelname)-8s │ %(name)-28s │ %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(console)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        settings.LOG_DIR / "leadflow.log",
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(file_handler)

    # Quiet external noisy loggers
    for lib in ("httpcore", "httpx", "urllib3", "openai", "googleapiclient"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    return logging.getLogger("leadflow.main")


logger = setup_logging()


class MetricsMiddleware:
    """Lightweight pure ASGI middleware for request metrics without BaseHTTPMiddleware overhead."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        global _api_requests_total, _api_errors_total
        _api_requests_total += 1
        status_code = 200

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            if status_code >= 500:
                _api_errors_total += 1
        except Exception:
            _api_errors_total += 1
            raise


# ── Security Headers Middleware ──────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.ENVIRONMENT == AppEnvironment.PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ── Application Lifespan ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown management."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} [{settings.ENVIRONMENT.value}]")
    
    # 1. Enforce fail-closed production validation
    settings.validate_production_readiness()
    
    # 2. Initialize database schema & seed default organization/user
    init_db(seed_default_tenant=True)

    yield

    logger.info(f"Shutting down {settings.APP_NAME}...")


# ── FastAPI App Creation ─────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Enterprise AI-Powered Outbound Intelligence & Campaign Delivery Platform",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.ENVIRONMENT != AppEnvironment.PRODUCTION else None,
    redoc_url=None,
)

# ── Middlewares ──────────────────────────────────────────────────────────────

app.add_middleware(MetricsMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Include Routers ──────────────────────────────────────────────────────────

app.include_router(api_router)

# ── Static UI & Dashboard Mounting ───────────────────────────────────────────

dashboard_dir = Path(__file__).resolve().parent / "dashboard"
static_dir = dashboard_dir / "static"
templates_dir = dashboard_dir / "templates"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the single-page application dashboard."""
    index_path = templates_dir / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>LeadFlow AI API is running</h1>")


@app.get("/health")
@app.get("/health/live")
def health_liveness():
    """Liveness probe for process supervision."""
    return {
        "status": "alive",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT.value,
    }


@app.get("/health/ready")
def health_readiness(response: Response):
    """
    Readiness probe verifying database and redis connectivity.
    Returns 200 OK if all required dependencies are reachable, or 503 if unavailable.
    """
    from sqlalchemy import text
    from database.database import get_session

    checks = {
        "database": "unknown",
        "redis": "skipped" if not settings.REDIS_URL else "unknown",
    }
    is_ready = True

    # 1. Verify Database
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        logger.error(f"Readiness check failed on database: {e}")
        checks["database"] = f"error: {str(e)}"
        is_ready = False

    # 2. Verify Redis if configured
    if settings.REDIS_URL:
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL, socket_timeout=1.5)
            r.ping()
            checks["redis"] = "connected"
        except Exception as e:
            logger.warning(f"Readiness check warning on redis: {e}")
            checks["redis"] = f"degraded: {str(e)}"
            # In graceful degradation mode, redis failure does not block API readiness if DB is alive

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if is_ready else "unready",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "checks": checks,
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics_endpoint():
    """Prometheus exposition metrics endpoint for monitoring."""
    from sqlalchemy import text
    from database.database import get_session

    redis_connected = 0
    if settings.REDIS_URL:
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL, socket_timeout=1.0)
            if r.ping():
                redis_connected = 1
        except Exception:
            redis_connected = 0

    pending_jobs = 0
    db_connections = 0
    try:
        with get_session() as session:
            res = session.execute(text("SELECT count(*) FROM send_jobs WHERE status = 'pending'")).scalar()
            pending_jobs = int(res) if res is not None else 0
            if "postgresql" in settings.DATABASE_URL:
                conn_res = session.execute(text("SELECT count(*) FROM pg_stat_activity")).scalar()
                db_connections = int(conn_res) if conn_res is not None else 0
            else:
                db_connections = 1
    except Exception:
        pass

    disk_info = shutil.disk_usage("/")
    req_total = _api_requests_total
    err_total = _api_errors_total

    lines = [
        "# HELP leadflow_api_requests_total Total HTTP requests processed by LeadFlow API",
        "# TYPE leadflow_api_requests_total counter",
        f"leadflow_api_requests_total {req_total}",
        "# HELP leadflow_api_errors_total Total 5xx or unhandled server errors",
        "# TYPE leadflow_api_errors_total counter",
        f"leadflow_api_errors_total {err_total}",
        "# HELP leadflow_queue_depth Pending email dispatch jobs in queue",
        "# TYPE leadflow_queue_depth gauge",
        f"leadflow_queue_depth {pending_jobs}",
        "# HELP leadflow_db_connections_active Number of active PostgreSQL database connections",
        "# TYPE leadflow_db_connections_active gauge",
        f"leadflow_db_connections_active {db_connections}",
        "# HELP leadflow_redis_connected Redis connectivity status (1 = connected, 0 = disconnected)",
        "# TYPE leadflow_redis_connected gauge",
        f"leadflow_redis_connected {redis_connected}",
        "# HELP leadflow_disk_free_bytes Free disk space in bytes",
        "# TYPE leadflow_disk_free_bytes gauge",
        f"leadflow_disk_free_bytes {disk_info.free}",
        "# HELP leadflow_disk_total_bytes Total disk space in bytes",
        "# TYPE leadflow_disk_total_bytes gauge",
        f"leadflow_disk_total_bytes {disk_info.total}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
