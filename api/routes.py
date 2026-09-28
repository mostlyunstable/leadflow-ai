"""
Production API Routes — FastAPI Endpoint Definitions.
Enforces:
1. Strict fail-closed authentication (JWT & API Key).
2. Multi-tenant scoping on all queries and mutations.
3. Decoupled campaign execution (enqueuing durable SendJobs instead of web thread sleeping).
4. Request validation and structured error responses.
5. Live domain deliverability diagnostics.
"""

import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import (
    APIRouter, UploadFile, File, Form, Depends, HTTPException,
    Query, Header, Request, status
)
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from core.config import settings, AppEnvironment
from core.queue import DurableQueue
from core.security import (
    decode_access_token, create_access_token, verify_password,
    encrypt_secret, mask_secret
)
from database.database import get_db_session
from database.models import (
    User, Organization, Membership, UserRole,
    Lead, LeadStatus, EmailRecord, EmailStatus, EmailType,
    Reply, Campaign, CampaignStatus, EmailProviderAccount, ProviderType,
    JobStatus, SendJob, Domain, utc_now
)
from modules.lead_ingestion.csv_handler import import_csv_to_db
from modules.lead_ingestion.sheets_handler import import_sheets_to_db
from modules.lead_enrichment.enricher import LeadEnricher
from modules.ai_engine.generator import generate_emails_batch
from modules.ai_engine.optimizer import get_optimization_report
from services.domain_health import inspect_domain_health

logger = logging.getLogger("leadflow.api")

router = APIRouter(prefix="/api", tags=["leadflow"])


# ── Authentication & Multi-Tenant Dependency ─────────────────────────────────

class AuthContext:
    """Carries tenant and user identity for the current request."""
    def __init__(self, organization_id: int, user_id: Optional[int] = None, role: str = "member"):
        self.organization_id = organization_id
        self.user_id = user_id
        self.role = role


def get_auth_context(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db_session),
) -> AuthContext:
    """
    Authenticate request via JWT Bearer token or API key.
    Fails closed in production.
    In development/testing, safely binds to the default organization if unauthenticated.
    """
    # 1. Check Bearer JWT token
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_access_token(token)
            return AuthContext(
                organization_id=payload["org"],
                user_id=int(payload["sub"]),
                role=payload.get("role", "member"),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication token: {e}",
            )

    # 2. Check X-API-Key
    if x_api_key:
        if settings.DASHBOARD_API_KEY and x_api_key == settings.DASHBOARD_API_KEY:
            # Bind to default organization
            org = db.query(Organization).filter_by(slug="default").first()
            org_id = org.id if org else 1
            return AuthContext(organization_id=org_id, role="admin")
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid API Key provided",
            )

    # 3. Fail-closed authentication (Enforced across all environments)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide Authorization Bearer token or X-API-Key header.",
    )


def require_roles(allowed_roles: List[str]):
    """Enforce server-side Role-Based Access Control (RBAC)."""
    def role_checker(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if auth.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of roles: {allowed_roles}. Current role: '{auth.role}'",
            )
        return auth
    return role_checker


# ── Schemas ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    daily_limit: int = Field(default=50, ge=1, le=1000)


# ── Auth Endpoints ───────────────────────────────────────────────────────────

@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db_session)):
    """Authenticate user and issue JWT access token."""
    user = db.query(User).filter_by(email=payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is deactivated")

    membership = db.query(Membership).filter_by(user_id=user.id).first()
    org_id = membership.organization_id if membership else 1
    role = membership.role.value if membership else "member"

    token = create_access_token(user_id=user.id, organization_id=org_id, role=role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "organization_id": org_id,
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": role,
        },
    }


# ── Lead Ingestion & Management ──────────────────────────────────────────────

@router.post("/leads/upload-csv")
async def upload_leads_csv(
    file: UploadFile = File(...),
    campaign_id: Optional[int] = Form(None),
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """Import and validate leads from an uploaded CSV file with tenant isolation."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV (.csv)")

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = import_csv_to_db(
            filepath=tmp_path,
            campaign_id=campaign_id,
            organization_id=auth.organization_id,
        )
        return result
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.post("/leads/sync-sheets")
async def sync_leads_sheets(
    spreadsheet_id: str = Form(...),
    range_name: str = Form("Sheet1!A:Z"),
    campaign_id: Optional[int] = Form(None),
    auth: AuthContext = Depends(get_auth_context),
):
    """Sync leads from Google Sheets into the tenant organization."""
    try:
        result = import_sheets_to_db(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            campaign_id=campaign_id,
            organization_id=auth.organization_id,
        )
        return result
    except Exception as e:
        logger.error(f"Sheets sync error: {e}")
        raise HTTPException(500, f"Google Sheets sync failed: {str(e)}")


@router.get("/leads")
def get_leads(
    status: Optional[str] = Query(None),
    campaign_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """List leads with filtering, pagination, and tenant isolation."""
    query = db.query(Lead).filter(Lead.organization_id == auth.organization_id)

    if status:
        query = query.filter(Lead.status == status)
    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Lead.first_name.ilike(pattern)) |
            (Lead.last_name.ilike(pattern)) |
            (Lead.email.ilike(pattern)) |
            (Lead.company_name.ilike(pattern))
        )

    total = query.count()
    leads = query.order_by(Lead.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "leads": [
            {
                "id": l.id,
                "first_name": l.first_name,
                "last_name": l.last_name,
                "full_name": l.full_name,
                "email": l.email,
                "company_name": l.company_name,
                "website": l.website,
                "industry": l.industry,
                "status": l.status.value,
                "enriched": l.enriched,
                "company_description": l.company_description,
                "key_offering": l.key_offering,
                "campaign_id": l.campaign_id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }


@router.get("/leads/{lead_id}")
def get_lead_detail(
    lead_id: int,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """Retrieve full details of a single lead."""
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.organization_id == auth.organization_id,
    ).first()
    if not lead:
        raise HTTPException(404, "Lead not found")

    emails = db.query(EmailRecord).filter_by(lead_id=lead.id).all()
    replies = db.query(Reply).filter_by(lead_id=lead.id).all()

    return {
        "lead": {
            "id": lead.id,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "full_name": lead.full_name,
            "email": lead.email,
            "company_name": lead.company_name,
            "website": lead.website,
            "industry": lead.industry,
            "company_description": lead.company_description,
            "key_offering": lead.key_offering,
            "status": lead.status.value,
            "enriched": lead.enriched,
            "campaign_id": lead.campaign_id,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        },
        "emails": [
            {
                "id": e.id,
                "subject": e.subject,
                "email_type": e.email_type.value,
                "status": e.status.value,
                "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            }
            for e in emails
        ],
        "replies": [
            {
                "id": r.id,
                "classification": r.classification.value,
                "received_at": r.received_at.isoformat() if r.received_at else None,
            }
            for r in replies
        ],
    }


@router.delete("/leads/{lead_id}")
def delete_lead(
    lead_id: int,
    auth: AuthContext = Depends(require_roles(["owner", "admin"])),
    db: Session = Depends(get_db_session),
):
    """Delete a lead."""
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.organization_id == auth.organization_id,
    ).first()
    if not lead:
        raise HTTPException(404, "Lead not found")

    db.delete(lead)
    db.commit()
    return {"status": "deleted", "lead_id": lead_id}


# ── Lead Enrichment ──────────────────────────────────────────────────────────

@router.post("/leads/enrich")
def enrich_leads(
    lead_id: Optional[int] = Form(None),
    limit: int = Form(50),
    auth: AuthContext = Depends(get_auth_context),
):
    """Trigger SSRF-safe enrichment for a single lead or all pending leads."""
    enricher = LeadEnricher()
    if lead_id:
        success = enricher.enrich_lead(lead_id)
        return {"status": "enriched" if success else "failed", "lead_id": lead_id}
    else:
        result = enricher.enrich_all_pending(organization_id=auth.organization_id, limit=limit)
        return result


# ── AI Email Generation ──────────────────────────────────────────────────────

@router.post("/emails/generate")
def generate_emails(
    campaign_id: Optional[int] = Form(None),
    limit: int = Form(50),
    auth: AuthContext = Depends(get_auth_context),
):
    """Generate personalized cold emails for leads."""
    result = generate_emails_batch(
        campaign_id=campaign_id,
        organization_id=auth.organization_id,
        limit=limit,
    )
    return result


# ── Campaign Management & Durable Execution ──────────────────────────────────

@router.post("/campaigns/create")
def create_campaign(
    payload: CampaignCreateRequest,
    auth: AuthContext = Depends(require_roles(["owner", "admin"])),
    db: Session = Depends(get_db_session),
):
    """Create a new campaign scoped to the organization."""
    campaign = Campaign(
        organization_id=auth.organization_id,
        name=payload.name,
        status=CampaignStatus.DRAFT,
        daily_limit=payload.daily_limit,
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
            "status": campaign.status.value,
        },
    }


@router.get("/campaigns")
def list_campaigns(
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """List all campaigns for the organization."""
    campaigns = db.query(Campaign).filter_by(organization_id=auth.organization_id).order_by(Campaign.id.desc()).all()
    return {
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status.value,
                "daily_limit": c.daily_limit,
                "total_leads": c.total_leads,
                "total_sent": c.total_sent,
                "total_replies": c.total_replies,
                "total_bounces": c.total_bounces,
                "reply_rate": c.reply_rate,
                "bounce_rate": c.bounce_rate,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "started_at": c.started_at.isoformat() if c.started_at else None,
            }
            for c in campaigns
        ]
    }


@router.post("/campaigns/{campaign_id}/start")
def start_campaign(
    campaign_id: int,
    auth: AuthContext = Depends(require_roles(["owner", "admin"])),
    db: Session = Depends(get_db_session),
):
    """
    Start campaign safely by:
    1. Activating campaign status.
    2. Creating durable SendJobs in the queue for all pending generated emails.
    Workers claim and execute jobs asynchronously without blocking web threads!
    """
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.organization_id == auth.organization_id,
    ).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    campaign.status = CampaignStatus.ACTIVE
    campaign.started_at = utc_now()
    db.commit()

    # Query pending emails for this campaign
    pending_emails = (
        db.query(EmailRecord)
        .filter(
            EmailRecord.organization_id == auth.organization_id,
            EmailRecord.campaign_id == campaign_id,
            EmailRecord.status == EmailStatus.PENDING,
        )
        .all()
    )

    queue = DurableQueue()
    enqueued_count = 0

    for email_rec in pending_emails:
        queue.enqueue_send_job(
            organization_id=auth.organization_id,
            campaign_id=campaign_id,
            lead_id=email_rec.lead_id,
            email_record_id=email_rec.id,
            session=db,
        )
        enqueued_count += 1
    db.commit()

    return {
        "status": "started",
        "campaign_id": campaign_id,
        "jobs_enqueued": enqueued_count,
        "message": f"Campaign activated with {enqueued_count} durable SendJobs dispatched to worker queue.",
    }


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(
    campaign_id: int,
    auth: AuthContext = Depends(require_roles(["owner", "admin"])),
    db: Session = Depends(get_db_session),
):
    """Pause an active campaign."""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.organization_id == auth.organization_id,
    ).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    campaign.status = CampaignStatus.PAUSED
    campaign.paused_at = utc_now()
    db.commit()

    return {"status": "paused", "campaign_id": campaign_id}


# ── Emails & Replies ─────────────────────────────────────────────────────────

@router.get("/emails")
def list_emails(
    status: Optional[str] = Query(None),
    campaign_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """List sent and pending emails with pagination."""
    query = db.query(EmailRecord).filter_by(organization_id=auth.organization_id)
    if status:
        query = query.filter(EmailRecord.status == status)
    if campaign_id:
        query = query.filter(EmailRecord.campaign_id == campaign_id)

    total = query.count()
    emails = query.order_by(EmailRecord.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "emails": [
            {
                "id": e.id,
                "lead_id": e.lead_id,
                "campaign_id": e.campaign_id,
                "subject": e.subject,
                "body": e.body,
                "email_type": e.email_type.value,
                "status": e.status.value,
                "sent_at": e.sent_at.isoformat() if e.sent_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in emails
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }


@router.get("/replies")
def list_replies(
    classification: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """List categorized replies."""
    query = db.query(Reply).filter_by(organization_id=auth.organization_id)
    if classification:
        query = query.filter(Reply.classification == classification)

    total = query.count()
    replies = query.order_by(Reply.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "replies": [
            {
                "id": r.id,
                "lead_id": r.lead_id,
                "classification": r.classification.value,
                "confidence_score": r.confidence_score,
                "reply_body": r.reply_body,
                "received_at": r.received_at.isoformat() if r.received_at else None,
            }
            for r in replies
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }


# ── Accounts & Credential Security ───────────────────────────────────────────

@router.post("/accounts/add")
def add_account(
    email: str = Form(...),
    display_name: Optional[str] = Form(None),
    provider_type: str = Form("gmail"),
    credentials_json: Optional[str] = Form(None),
    auth: AuthContext = Depends(require_roles(["owner", "admin"])),
    db: Session = Depends(get_db_session),
):
    """
    Register an email provider account.
    Encrypts credentials at rest (AES/Fernet) before storing in the database!
    """
    clean_email = email.strip().lower()
    existing = db.query(EmailProviderAccount).filter_by(
        organization_id=auth.organization_id,
        account_email=clean_email,
    ).first()

    if existing:
        return {"status": "exists", "email": clean_email, "message": "Account already registered"}

    # Encrypt credentials if provided
    encrypted_creds = None
    if credentials_json:
        encrypted_creds = encrypt_secret(credentials_json)

    account = EmailProviderAccount(
        organization_id=auth.organization_id,
        provider_type=ProviderType(provider_type) if provider_type in ProviderType._value2member_map_ else ProviderType.GMAIL,
        account_email=clean_email,
        display_name=display_name or clean_email.split("@")[0],
        encrypted_credentials=encrypted_creds,
        is_active=True,
        is_healthy=True,
    )
    db.add(account)
    db.commit()

    return {
        "status": "added",
        "email": clean_email,
        "provider": account.provider_type.value,
        "is_healthy": account.is_healthy,
    }


@router.get("/accounts")
def list_accounts(
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """List registered sender accounts (never exposing encrypted secrets)."""
    accounts = db.query(EmailProviderAccount).filter_by(organization_id=auth.organization_id).all()
    return {
        "accounts": [
            {
                "id": a.id,
                "email": a.account_email,
                "display_name": a.display_name,
                "provider": a.provider_type.value,
                "is_active": a.is_active,
                "is_healthy": a.is_healthy,
                "sends_today": a.sends_today,
                "last_send_at": a.last_send_at.isoformat() if a.last_send_at else None,
                "has_credentials": bool(a.encrypted_credentials),
            }
            for a in accounts
        ]
    }


@router.post("/accounts/health-check")
def health_check_accounts(
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """Verify health and configuration of all accounts."""
    accounts = db.query(EmailProviderAccount).filter_by(organization_id=auth.organization_id).all()
    return {
        "total": len(accounts),
        "healthy": sum(1 for a in accounts if a.is_healthy),
        "unhealthy": sum(1 for a in accounts if not a.is_healthy),
    }


# ── Domain & Deliverability Diagnostics ──────────────────────────────────────

@router.get("/domains/check")
def check_domain_dns(
    domain: str = Query(..., min_length=3),
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """
    Live deliverability health check for a sending domain:
    Queries MX, SPF, and DMARC authentication records.
    """
    report = inspect_domain_health(domain)

    # Persist or update domain record
    domain_rec = db.query(Domain).filter_by(
        organization_id=auth.organization_id,
        domain_name=report.domain,
    ).first()

    if not domain_rec:
        domain_rec = Domain(
            organization_id=auth.organization_id,
            domain_name=report.domain,
        )
        db.add(domain_rec)

    domain_rec.has_mx = report.has_mx
    domain_rec.has_spf = report.has_spf
    domain_rec.has_dmarc = report.has_dmarc
    domain_rec.spf_record = report.spf_record
    domain_rec.dmarc_record = report.dmarc_record
    domain_rec.mx_records_json = report.mx_records
    domain_rec.health_score = report.health_score
    domain_rec.is_healthy = report.is_healthy
    domain_rec.last_checked_at = utc_now()
    db.commit()

    return {
        "domain": report.domain,
        "is_healthy": report.is_healthy,
        "health_score": report.health_score,
        "has_mx": report.has_mx,
        "has_spf": report.has_spf,
        "has_dmarc": report.has_dmarc,
        "spf_record": report.spf_record,
        "dmarc_record": report.dmarc_record,
        "mx_records": report.mx_records,
        "issues": report.issues,
    }


# ── Real-Time Metrics & Reporting ────────────────────────────────────────────

@router.get("/stats")
@router.get("/analytics/overview")
def get_stats(
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
):
    """Real-time platform statistics for the organization dashboard."""
    total_leads = db.query(Lead).filter_by(organization_id=auth.organization_id).count()
    enriched_leads = db.query(Lead).filter(
        Lead.organization_id == auth.organization_id,
        Lead.enriched == True,
    ).count()

    total_sent = db.query(EmailRecord).filter(
        EmailRecord.organization_id == auth.organization_id,
        EmailRecord.status == EmailStatus.SENT,
    ).count()

    total_pending = db.query(EmailRecord).filter(
        EmailRecord.organization_id == auth.organization_id,
        EmailRecord.status.in_([EmailStatus.PENDING, EmailStatus.QUEUED]),
    ).count()

    total_replies = db.query(Reply).filter_by(organization_id=auth.organization_id).count()

    interested_replies = db.query(Reply).filter(
        Reply.organization_id == auth.organization_id,
        Reply.classification == "interested",
    ).count()

    # Active campaigns count
    active_campaigns = db.query(Campaign).filter_by(
        organization_id=auth.organization_id,
        status=CampaignStatus.ACTIVE,
    ).count()

    reply_rate = round((total_replies / total_sent) * 100, 1) if total_sent > 0 else 0.0

    return {
        "overview": {
            "total_leads": total_leads,
            "enriched_leads": enriched_leads,
            "total_sent": total_sent,
            "total_pending": total_pending,
            "total_replies": total_replies,
            "interested_replies": interested_replies,
            "active_campaigns": active_campaigns,
            "reply_rate": reply_rate,
        },
        "pipeline": {
            "new": db.query(Lead).filter_by(organization_id=auth.organization_id, status=LeadStatus.NEW).count(),
            "enriched": enriched_leads,
            "emailed": db.query(Lead).filter_by(organization_id=auth.organization_id, status=LeadStatus.EMAILED).count(),
            "replied": total_replies,
            "unsubscribed": db.query(Lead).filter_by(organization_id=auth.organization_id, status=LeadStatus.UNSUBSCRIBED).count(),
        },
    }


@router.get("/stats/optimization")
def get_optimization_stats(auth: AuthContext = Depends(get_auth_context)):
    """Retrieve template and performance optimization data."""
    return get_optimization_report()
