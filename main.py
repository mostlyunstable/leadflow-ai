"""
LeadFlow AI — Cold Email Outreach System
Main application entry point.

Initializes FastAPI server, database, background schedulers,
and serves the dashboard UI.
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config.settings import HOST, PORT, DEBUG, LOG_LEVEL, LOG_DIR, REPLY_CHECK_INTERVAL_MINUTES
from database.database import init_db

# ── Logging Setup ────────────────────────────────────────────────────────────

def setup_logging():
    """Configure structured logging to console and file."""
    log_format = "%(asctime)s │ %(levelname)-8s │ %(name)-30s │ %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Root logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(LOG_DIR / "outreach.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(file_handler)

    # Quiet noisy loggers
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    return logging.getLogger("leadflow")


logger = setup_logging()


# ── Background Scheduler ────────────────────────────────────────────────────

_scheduler = None

def start_scheduler():
    """Start APScheduler for follow-up and reply monitoring jobs."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = BackgroundScheduler()

        # Reply monitoring job — check every N minutes
        def check_replies_job():
            try:
                from modules.reply_tracker.monitor import InboxMonitor
                monitor = InboxMonitor()
                result = monitor.check_all_accounts()
                if result["new_replies"] > 0 or result["bounces"] > 0:
                    logger.info(f"Inbox check: {result['new_replies']} replies, {result['bounces']} bounces")
            except Exception as e:
                logger.error(f"Reply check job failed: {e}")

        _scheduler.add_job(
            check_replies_job,
            trigger=IntervalTrigger(minutes=REPLY_CHECK_INTERVAL_MINUTES),
            id="reply_check",
            name="Check inbox for replies",
            replace_existing=True,
        )

        # Follow-up scheduling job — check every hour
        def check_followups_job():
            try:
                from modules.scheduler.followup_scheduler import FollowUpScheduler
                scheduler = FollowUpScheduler()
                result = scheduler.check_and_queue_followups()
                if result["followup_1_queued"] > 0 or result["followup_2_queued"] > 0:
                    logger.info(f"Follow-ups queued: {result}")
            except Exception as e:
                logger.error(f"Follow-up check job failed: {e}")

        _scheduler.add_job(
            check_followups_job,
            trigger=IntervalTrigger(hours=1),
            id="followup_check",
            name="Check and queue follow-ups",
            replace_existing=True,
        )

        # Warmup increment job — run daily at midnight
        def warmup_increment_job():
            try:
                from config.settings import WARMUP_ENABLED, WARMUP_INCREMENT
                if not WARMUP_ENABLED:
                    return
                from database.database import get_session
                from database.models import Campaign, CampaignStatus
                with get_session() as session:
                    active = session.query(Campaign).filter_by(status=CampaignStatus.ACTIVE).all()
                    for campaign in active:
                        if campaign.current_daily_limit < campaign.daily_limit:
                            campaign.current_daily_limit = min(
                                campaign.current_daily_limit + WARMUP_INCREMENT,
                                campaign.daily_limit,
                            )
                            campaign.warmup_day += 1
                            logger.info(
                                f"Campaign '{campaign.name}' warmup day {campaign.warmup_day}: "
                                f"limit increased to {campaign.current_daily_limit}"
                            )
            except Exception as e:
                logger.error(f"Warmup increment job failed: {e}")

        _scheduler.add_job(
            warmup_increment_job,
            trigger=IntervalTrigger(hours=24),
            id="warmup_increment",
            name="Increment warmup limits",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info(
            f"Background scheduler started: "
            f"reply check every {REPLY_CHECK_INTERVAL_MINUTES}min, "
            f"follow-up check every 1hr"
        )

    except ImportError:
        logger.warning(
            "APScheduler not installed — background jobs disabled. "
            "Install with: pip install apscheduler"
        )
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # Startup
    logger.info("=" * 60)
    logger.info("  LeadFlow AI — Cold Email Outreach System")
    logger.info("=" * 60)

    init_db()
    start_scheduler()

    logger.info(f"Dashboard: http://localhost:{PORT}")
    logger.info(f"API Docs:  http://localhost:{PORT}/docs")
    logger.info("=" * 60)

    yield

    # Shutdown
    stop_scheduler()
    logger.info("Application shutdown complete")


# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="LeadFlow AI",
    description="AI-Powered Cold Email Outreach System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
BASE_DIR = Path(__file__).resolve().parent
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "dashboard" / "static")),
    name="static",
)

# API routes
from api.routes import router as api_router
app.include_router(api_router)


# Dashboard route
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the dashboard UI."""
    template_path = BASE_DIR / "dashboard" / "templates" / "index.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


# Health endpoint
@app.get("/health")
async def health():
    """Simple health check."""
    return {"status": "healthy", "service": "LeadFlow AI"}


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level=LOG_LEVEL.lower(),
    )
