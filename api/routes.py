"""
API Routes — FastAPI endpoint definitions for the outreach system.
Handles lead management, campaign control, email operations, and dashboard data.
"""

import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query, Header, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config.settings import DASHBOARD_API_KEY
from database.database import get_db_session, get_session
from database.models import (
    Lead, LeadStatus, EmailRecord, EmailStatus, EmailType,
    Reply, Campaign, CampaignStatus, GmailAccount,
)
from modules.lead_ingestion.csv_handler import import_csv_to_db
from modules.lead_ingestion.sheets_handler import import_sheets_to_db
from modules.lead_enrichment.enricher import LeadEnricher
from modules.ai_engine.generator import generate_emails_batch
from modules.ai_engine.optimizer import get_optimization_report
from modules.email_sender.batch_sender import BatchSender
from modules.email_sender.account_manager import AccountManager
from modules.reply_tracker.monitor import InboxMonitor
from modules.scheduler.followup_scheduler import FollowUpScheduler

logger = logging.getLogger(__name__)

# ── Simple in-memory rate limiter ──────────────────────────────────────────
_rate_limits: dict[str, list[float]] = {}
_rate_lock = threading.Lock()
MAX_REQUESTS_PER_MINUTE = 60


def _check_rate_limit(client_ip: str = "global"):
    """Reject requests if the client exceeds the per-minute limit."""
    now = time.time()
    with _rate_lock:
        timestamps = _rate_limits.setdefault(client_ip, [])
        # Remove timestamps older than 60 seconds
        timestamps[:] = [t for t in timestamps if now - t < 60]
        if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
        timestamps.append(now)

def verify_api_key(x_api_key: str = Header(None)):
    """Verify the API key if one is configured."""
    if DASHBOARD_API_KEY and x_api_key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    _check_rate_limit()

router = APIRouter(prefix="/api", tags=["outreach"], dependencies=[Depends(verify_api_key)])

# ── Shared instances ─────────────────────────────────────────────────────────
_batch_senders: dict[int, BatchSender] = {}  # per-campaign senders to avoid race conditions
_enricher = LeadEnricher()
_inbox_monitor = InboxMonitor()
_followup_scheduler = FollowUpScheduler()


# ══════════════════════════════════════════════════════════════════════════════
#  LEAD MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/leads/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    campaign_id: Optional[int] = Form(None),
):
    """Upload a CSV file to import leads."""
    if not file.filename.endswith((".csv", ".CSV")):
        raise HTTPException(400, "Only CSV files are accepted")

    content = await file.read()

    result = import_csv_to_db(content, campaign_id=campaign_id)

    # Update campaign stats
    if campaign_id:
        _update_campaign_lead_count(campaign_id)

    return JSONResponse({
        "status": "success",
        "imported": result["imported"],
        "stats": result["stats"],
        "errors": result["errors"][:10],  # Limit error output
    })


@router.post("/leads/sync-sheets")
async def sync_sheets(
    spreadsheet_url: str = Form(...),
    worksheet_name: Optional[str] = Form(None),
    campaign_id: Optional[int] = Form(None),
):
    """Import leads from a Google Sheet."""
    result = import_sheets_to_db(spreadsheet_url, worksheet_name, campaign_id)

    if campaign_id:
        _update_campaign_lead_count(campaign_id)

    return JSONResponse({
        "status": "success",
        "imported": result["imported"],
        "stats": result["stats"],
        "errors": result["errors"][:10],
    })


@router.get("/leads")
async def list_leads(
    status: Optional[str] = Query(None),
    campaign_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
):
    """List leads with optional filtering and pagination."""
    query = db.query(Lead)

    if status:
        try:
            lead_status = LeadStatus(status)
            query = query.filter(Lead.status == lead_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)

    total = query.count()
    leads = (
        query.order_by(Lead.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "leads": [
            {
                "id": l.id,
                "first_name": l.first_name,
                "last_name": l.last_name,
                "email": l.email,
                "company_name": l.company_name,
                "website": l.website,
                "industry": l.industry,
                "status": l.status.value,
                "enriched": l.enriched,
                "source": l.source,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
    }


@router.delete("/leads/{lead_id}")
async def delete_lead(lead_id: int, db: Session = Depends(get_db_session)):
    """Delete a lead and all associated records."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    db.delete(lead)
    db.commit()
    return {"status": "deleted", "lead_id": lead_id}


# ══════════════════════════════════════════════════════════════════════════════
#  ENRICHMENT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/leads/enrich")
async def enrich_leads(background_tasks: BackgroundTasks, campaign_id: Optional[int] = Form(None)):
    """Trigger enrichment for all unenriched leads (runs in background)."""
    def _run_enrichment():
        try:
            result = _enricher.enrich_all_pending(delay=1.5)
            logger.info(f"Enrichment complete: {result}")
        except Exception as e:
            logger.error(f"Enrichment failed: {e}")

    background_tasks.add_task(_run_enrichment)

    return {"status": "enrichment_started", "message": "Running in background"}


# ══════════════════════════════════════════════════════════════════════════════
#  AI EMAIL GENERATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/emails/generate")
async def generate_emails(
    background_tasks: BackgroundTasks,
    campaign_id: Optional[int] = Form(None),
    limit: int = Form(50),
):
    """Generate personalized emails for leads that don't have one yet."""
    def _run_generation():
        try:
            result = generate_emails_batch(campaign_id=campaign_id, limit=limit)
            logger.info(f"Email generation complete: {result}")
        except Exception as e:
            logger.error(f"Email generation failed: {e}")

    background_tasks.add_task(_run_generation)

    return {"status": "generation_started", "message": f"Generating up to {limit} emails"}


# ══════════════════════════════════════════════════════════════════════════════
#  CAMPAIGN MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/campaigns/create")
async def create_campaign(
    name: str = Form(...),
    daily_limit: int = Form(50),
    db: Session = Depends(get_db_session),
):
    """Create a new campaign."""
    campaign = Campaign(
        name=name,
        daily_limit=daily_limit,
        current_daily_limit=min(10, daily_limit),  # Start with warmup limit
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return {
        "status": "created",
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "daily_limit": campaign.daily_limit,
        },
    }


@router.get("/campaigns")
async def list_campaigns(db: Session = Depends(get_db_session)):
    """List all campaigns."""
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return {
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status.value,
                "daily_limit": c.daily_limit,
                "current_daily_limit": c.current_daily_limit,
                "total_leads": c.total_leads,
                "total_sent": c.total_sent,
                "total_replies": c.total_replies,
                "total_bounces": c.total_bounces,
                "reply_rate": c.reply_rate,
                "bounce_rate": c.bounce_rate,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in campaigns
        ],
    }


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db_session)):
    """Start a campaign — begins sending pending emails."""
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    from datetime import datetime, timezone
    campaign.status = CampaignStatus.ACTIVE
    campaign.started_at = datetime.now(timezone.utc)
    db.commit()

    # Start sending in background — use per-campaign sender
    def _run_send():
        try:
            sender = BatchSender()
            _batch_senders[campaign_id] = sender
            result = sender.send_pending_emails(campaign_id=campaign_id)
            logger.info(f"Campaign {campaign_id} send complete: {result}")
        except Exception as e:
            logger.error(f"Campaign {campaign_id} send failed: {e}")
        finally:
            _batch_senders.pop(campaign_id, None)

    background_tasks.add_task(_run_send)

    return {"status": "started", "campaign_id": campaign_id}


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: Session = Depends(get_db_session)):
    """Pause a running campaign."""
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    from datetime import datetime, timezone
    campaign.status = CampaignStatus.PAUSED
    campaign.paused_at = datetime.now(timezone.utc)
    db.commit()

    sender = _batch_senders.get(campaign_id)
    if sender:
        sender.stop()

    return {"status": "paused", "campaign_id": campaign_id}


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL RECORDS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/emails")
async def list_emails(
    status: Optional[str] = Query(None),
    email_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
):
    """List email records with filtering."""
    query = db.query(EmailRecord)

    if status:
        try:
            query = query.filter(EmailRecord.status == EmailStatus(status))
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    if email_type:
        try:
            query = query.filter(EmailRecord.email_type == EmailType(email_type))
        except ValueError:
            raise HTTPException(400, f"Invalid email type: {email_type}")

    total = query.count()
    records = (
        query.order_by(EmailRecord.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "emails": [
            {
                "id": r.id,
                "lead_id": r.lead_id,
                "subject": r.subject,
                "body": r.body[:200] + "..." if len(r.body) > 200 else r.body,
                "email_type": r.email_type.value,
                "status": r.status.value,
                "gmail_account": r.gmail_account,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "retry_count": r.retry_count,
                "error_message": r.error_message,
            }
            for r in records
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  REPLIES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/replies")
async def list_replies(
    classification: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
):
    """List all received replies with classifications."""
    query = db.query(Reply)

    if classification:
        try:
            from database.models import ReplyClassification
            query = query.filter(
                Reply.classification == ReplyClassification(classification)
            )
        except ValueError:
            raise HTTPException(400, f"Invalid classification: {classification}")

    total = query.count()
    replies = (
        query.order_by(Reply.received_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "replies": [
            {
                "id": r.id,
                "lead_id": r.lead_id,
                "reply_body": r.reply_body[:300] + "..." if len(r.reply_body) > 300 else r.reply_body,
                "classification": r.classification.value,
                "confidence": r.confidence_score,
                "received_at": r.received_at.isoformat() if r.received_at else None,
            }
            for r in replies
        ],
    }


@router.post("/replies/check")
async def check_replies(background_tasks: BackgroundTasks):
    """Trigger immediate inbox check for new replies."""
    def _run_check():
        try:
            result = _inbox_monitor.check_all_accounts()
            logger.info(f"Reply check complete: {result}")
        except Exception as e:
            logger.error(f"Reply check failed: {e}")

    background_tasks.add_task(_run_check)

    return {"status": "checking", "message": "Checking all inboxes for new replies"}


# ══════════════════════════════════════════════════════════════════════════════
#  FOLLOW-UPS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/followups/check")
async def check_followups(background_tasks: BackgroundTasks, campaign_id: Optional[int] = Form(None)):
    """Trigger follow-up check and queue eligible follow-ups."""
    def _run_followups():
        try:
            result = _followup_scheduler.check_and_queue_followups(campaign_id)
            logger.info(f"Follow-up check: {result}")
        except Exception as e:
            logger.error(f"Follow-up check failed: {e}")

    background_tasks.add_task(_run_followups)

    return {"status": "checking", "message": "Checking for pending follow-ups"}


@router.get("/followups/status")
async def followup_status(campaign_id: Optional[int] = Query(None)):
    """Get follow-up pipeline status."""
    return _followup_scheduler.get_followup_status(campaign_id)


# ══════════════════════════════════════════════════════════════════════════════
#  GMAIL ACCOUNTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/accounts/add")
async def add_gmail_account(
    email: str = Form(...),
    display_name: Optional[str] = Form(None),
):
    """Add a Gmail account for sending. Will trigger OAuth flow."""
    manager = AccountManager()
    result = manager.add_account(email, display_name)

    if result["status"] == "auth_failed":
        raise HTTPException(400, f"Authentication failed: {result.get('error')}")

    return result


@router.get("/accounts")
async def list_accounts():
    """List all registered Gmail accounts."""
    manager = AccountManager()
    return {"accounts": manager.list_accounts()}


@router.post("/accounts/health-check")
async def health_check_accounts():
    """Run health check on all Gmail accounts."""
    manager = AccountManager()
    return manager.health_check_all()


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD STATS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_stats(
    campaign_id: Optional[int] = Query(None),
    db: Session = Depends(get_db_session),
):
    """Get comprehensive dashboard statistics."""
    # Base queries
    lead_query = db.query(Lead)
    email_query = db.query(EmailRecord)
    reply_query = db.query(Reply)

    if campaign_id:
        lead_query = lead_query.filter(Lead.campaign_id == campaign_id)
        email_query = email_query.join(Lead).filter(Lead.campaign_id == campaign_id)
        reply_query = reply_query.join(Lead).filter(Lead.campaign_id == campaign_id)

    total_leads = lead_query.count()
    total_sent = email_query.filter(EmailRecord.status == EmailStatus.SENT).count()
    total_pending = email_query.filter(
        EmailRecord.status.in_([EmailStatus.PENDING, EmailStatus.QUEUED])
    ).count()
    total_failed = email_query.filter(EmailRecord.status == EmailStatus.FAILED).count()
    total_bounced = email_query.filter(EmailRecord.status == EmailStatus.BOUNCED).count()
    total_replies = reply_query.count()

    # Reply classifications
    from database.models import ReplyClassification
    interested = reply_query.filter(
        Reply.classification == ReplyClassification.INTERESTED
    ).count()
    not_interested = reply_query.filter(
        Reply.classification == ReplyClassification.NOT_INTERESTED
    ).count()

    # Rates
    reply_rate = round((total_replies / total_sent * 100), 1) if total_sent > 0 else 0
    bounce_rate = round((total_bounced / total_sent * 100), 1) if total_sent > 0 else 0
    interested_rate = round((interested / total_sent * 100), 1) if total_sent > 0 else 0

    # Status breakdown
    status_breakdown = {}
    for status in LeadStatus:
        count = lead_query.filter(Lead.status == status).count()
        if count > 0:
            status_breakdown[status.value] = count

    return {
        "overview": {
            "total_leads": total_leads,
            "total_sent": total_sent,
            "total_pending": total_pending,
            "total_failed": total_failed,
            "total_bounced": total_bounced,
            "total_replies": total_replies,
            "interested": interested,
            "not_interested": not_interested,
        },
        "rates": {
            "reply_rate": reply_rate,
            "bounce_rate": bounce_rate,
            "interested_rate": interested_rate,
        },
        "lead_status_breakdown": status_breakdown,
    }


@router.get("/stats/optimization")
async def get_optimization_stats():
    """Get email optimization insights."""
    return get_optimization_report()


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _update_campaign_lead_count(campaign_id: int):
    """Helper to update campaign lead count."""
    with get_session() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign:
            campaign.total_leads = (
                session.query(Lead)
                .filter(Lead.campaign_id == campaign_id)
                .count()
            )
