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
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

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
def health_check():
    """Health & Readiness probe for orchestrators/Docker."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT.value,
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
