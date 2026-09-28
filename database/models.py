"""
Production Database Models — SQLAlchemy 2.0 ORM.
Implements:
1. Multi-tenant isolation (Organization, User, Membership).
2. Lead & Company entities.
3. Campaign & Recipient lifecycle.
4. Durable SendJob & SendAttempt state machine with worker leases and idempotency.
5. EmailProviderAccount with encrypted credentials at rest.
6. EnrichmentJob & EnrichmentResult with SSRF audit flags.
7. Domain & DNS diagnostic records (SPF, DKIM, DMARC, MX).
8. AuditLog & Event tracking.
"""

from datetime import datetime, timezone
import enum
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, Enum as SQLEnum, UniqueConstraint, Index, JSON
)
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


# ── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class LeadStatus(str, enum.Enum):
    NEW = "new"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    EMAIL_GENERATED = "email_generated"
    QUEUED = "queued"
    EMAILED = "emailed"
    FOLLOWUP_1_SENT = "followup_1_sent"
    FOLLOWUP_2_SENT = "followup_2_sent"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class EmailType(str, enum.Enum):
    INITIAL = "initial"
    FOLLOWUP_1 = "followup_1"
    FOLLOWUP_2 = "followup_2"


class EmailStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProviderType(str, enum.Enum):
    GMAIL = "gmail"
    SMTP = "smtp"
    MOCK = "mock"


class ReplyClassification(str, enum.Enum):
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    SPAM = "spam"
    UNKNOWN = "unknown"


class SuppressionReason(str, enum.Enum):
    UNSUBSCRIBE = "unsubscribe"
    BOUNCE = "bounce"
    COMPLAINT = "complaint"
    MANUAL = "manual"


# ── Multi-Tenancy Core ───────────────────────────────────────────────────────

class Organization(Base):
    """Tenant boundary entity. All resources are strictly scoped to an organization."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    memberships = relationship("Membership", back_populates="organization", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="organization", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="organization", cascade="all, delete-orphan")
    accounts = relationship("EmailProviderAccount", back_populates="organization", cascade="all, delete-orphan")
    domains = relationship("Domain", back_populates="organization", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="organization", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Organization id={self.id} slug='{self.slug}'>"


class User(Base):
    """User account entity for authentication and audit tracking."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User id={self.id} email='{self.email}'>"


class Membership(Base):
    """User membership within an organization with role-based access control."""
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SQLEnum(UserRole), default=UserRole.MEMBER, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    user = relationship("User", back_populates="memberships")
    organization = relationship("Organization", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_organization"),
    )


# ── Lead & Company Domain ────────────────────────────────────────────────────

class Company(Base):
    """Enriched company profile scoped to organization."""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=True, index=True)
    website = Column(String(500), nullable=True)
    industry = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    key_offering = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    leads = relationship("Lead", back_populates="company")

    __table_args__ = (
        Index("ix_companies_org_domain", "organization_id", "domain"),
    )


class Lead(Base):
    """A sales prospect scoped to an organization."""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)

    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    website = Column(String(500), nullable=True)
    industry = Column(String(200), nullable=True)

    # Enrichment fields (denormalized for convenience)
    company_description = Column(Text, nullable=True)
    key_offering = Column(Text, nullable=True)
    enriched = Column(Boolean, default=False, nullable=False)

    # Status tracking
    status = Column(SQLEnum(LeadStatus), default=LeadStatus.NEW, nullable=False, index=True)
    source = Column(String(50), default="csv", nullable=False)  # csv, sheets, manual, api
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="leads")
    company = relationship("Company", back_populates="leads")
    campaign = relationship("Campaign", back_populates="leads")
    emails = relationship("EmailRecord", back_populates="lead", cascade="all, delete-orphan")
    send_jobs = relationship("SendJob", back_populates="lead", cascade="all, delete-orphan")
    replies = relationship("Reply", back_populates="lead", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_org_lead_email"),
        Index("ix_leads_org_status", "organization_id", "status"),
        Index("ix_leads_org_campaign", "organization_id", "campaign_id"),
    )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


# ── Campaign Domain ──────────────────────────────────────────────────────────

class Campaign(Base):
    """An outbound campaign grouping leads with policies and metrics."""
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(SQLEnum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False, index=True)

    daily_limit = Column(Integer, default=50, nullable=False)
    current_daily_limit = Column(Integer, default=10, nullable=False)
    warmup_day = Column(Integer, default=0, nullable=False)

    # Real-time metrics
    total_leads = Column(Integer, default=0, nullable=False)
    total_sent = Column(Integer, default=0, nullable=False)
    total_replies = Column(Integer, default=0, nullable=False)
    total_bounces = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="campaigns")
    leads = relationship("Lead", back_populates="campaign")
    send_jobs = relationship("SendJob", back_populates="campaign", cascade="all, delete-orphan")

    @property
    def reply_rate(self) -> float:
        return round((self.total_replies / self.total_sent) * 100, 1) if self.total_sent > 0 else 0.0

    @property
    def bounce_rate(self) -> float:
        return round((self.total_bounces / self.total_sent) * 100, 1) if self.total_sent > 0 else 0.0


# ── Email & Durable Job Execution State Machine ──────────────────────────────

class EmailRecord(Base):
    """Persistent representation of generated or scheduled email content."""
    __tablename__ = "email_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)

    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    email_type = Column(SQLEnum(EmailType), default=EmailType.INITIAL, nullable=False)
    status = Column(SQLEnum(EmailStatus), default=EmailStatus.PENDING, nullable=False, index=True)

    # Provider and tracking fields
    provider_name = Column(String(50), default="gmail", nullable=False)
    provider_account = Column(String(255), nullable=True)
    provider_message_id = Column(String(255), nullable=True, unique=True, index=True)
    provider_thread_id = Column(String(255), nullable=True, index=True)
    idempotency_key = Column(String(128), nullable=False, unique=True, index=True)

    retry_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    scheduled_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    lead = relationship("Lead", back_populates="emails")
    replies = relationship("Reply", back_populates="email_record", cascade="all, delete-orphan")
    send_jobs = relationship("SendJob", back_populates="email_record")

    __table_args__ = (
        Index("ix_email_records_org_status", "organization_id", "status"),
        Index("ix_email_records_lead_type", "lead_id", "email_type"),
    )


class SendJob(Base):
    """
    Durable queue job entity.
    Tracks state machine: PENDING -> QUEUED -> PROCESSING -> (SENT | RETRY_WAIT | FAILED | CANCELLED).
    Includes worker leases and idempotency keys to prevent duplicate execution across workers.
    """
    __tablename__ = "send_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    email_record_id = Column(Integer, ForeignKey("email_records.id", ondelete="CASCADE"), nullable=False, index=True)

    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False, unique=True, index=True)

    # Worker lease lock
    lease_worker_id = Column(String(100), nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)

    # Retry and scheduling
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    scheduled_for = Column(DateTime, default=utc_now, nullable=False, index=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    campaign = relationship("Campaign", back_populates="send_jobs")
    lead = relationship("Lead", back_populates="send_jobs")
    email_record = relationship("EmailRecord", back_populates="send_jobs")
    attempts = relationship("SendAttempt", back_populates="send_job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_send_jobs_poll", "status", "scheduled_for", "lease_expires_at"),
    )


class SendAttempt(Base):
    """Atomic attempt audit record for every execution of a SendJob."""
    __tablename__ = "send_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    send_job_id = Column(Integer, ForeignKey("send_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    worker_id = Column(String(100), nullable=False)

    status = Column(String(50), nullable=False)  # success, transient_failure, permanent_failure
    provider_name = Column(String(50), nullable=False)
    provider_response_code = Column(String(50), nullable=True)
    provider_message_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, default=utc_now, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    # Relationships
    send_job = relationship("SendJob", back_populates="attempts")


# ── Providers & Credential Security ──────────────────────────────────────────

class EmailProviderAccount(Base):
    """Registered sender account with encrypted credentials at rest."""
    __tablename__ = "email_provider_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_type = Column(SQLEnum(ProviderType), default=ProviderType.GMAIL, nullable=False)
    account_email = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)

    # Encrypted credentials (AES-128-CBC / Fernet ciphertext)
    encrypted_credentials = Column(Text, nullable=True)

    # Sending policy and health tracking
    is_active = Column(Boolean, default=True, nullable=False)
    is_healthy = Column(Boolean, default=True, nullable=False)
    sends_today = Column(Integer, default=0, nullable=False)
    sends_this_hour = Column(Integer, default=0, nullable=False)
    last_send_at = Column(DateTime, nullable=True)
    last_reset_date = Column(String(10), nullable=True)  # YYYY-MM-DD
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="accounts")

    __table_args__ = (
        UniqueConstraint("organization_id", "account_email", name="uq_org_account_email"),
        Index("ix_provider_accounts_org_active", "organization_id", "is_active", "is_healthy"),
    )


# ── Lead Enrichment Domain ───────────────────────────────────────────────────

class EnrichmentJob(Base):
    """Durable job for web scraping and AI summarization with lease locks."""
    __tablename__ = "enrichment_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    target_url = Column(String(500), nullable=False)

    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)
    lease_worker_id = Column(String(100), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=2, nullable=False)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class EnrichmentResult(Base):
    """Audit record and extracted data from website scraping and AI analysis."""
    __tablename__ = "enrichment_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    target_url = Column(String(500), nullable=False)
    resolved_ip = Column(String(45), nullable=True)

    fetch_method = Column(String(50), default="http", nullable=False)  # http, browser
    http_status = Column(Integer, nullable=True)
    title = Column(String(500), nullable=True)
    meta_description = Column(Text, nullable=True)
    headings_json = Column(JSON, nullable=True)
    extracted_text = Column(Text, nullable=True)
    summary_description = Column(Text, nullable=True)
    key_offering = Column(Text, nullable=True)
    confidence_score = Column(Float, default=0.0, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)


# ── Domain & Health Diagnostics ──────────────────────────────────────────────

class Domain(Base):
    """Tracked sending domain with DNS authentication verification records."""
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    domain_name = Column(String(255), nullable=False)

    has_mx = Column(Boolean, default=False, nullable=False)
    has_spf = Column(Boolean, default=False, nullable=False)
    has_dkim = Column(Boolean, default=False, nullable=False)
    has_dmarc = Column(Boolean, default=False, nullable=False)

    spf_record = Column(Text, nullable=True)
    dmarc_record = Column(Text, nullable=True)
    mx_records_json = Column(JSON, nullable=True)

    is_healthy = Column(Boolean, default=False, nullable=False)
    health_score = Column(Float, default=0.0, nullable=False)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="domains")

    __table_args__ = (
        UniqueConstraint("organization_id", "domain_name", name="uq_org_domain"),
    )


# ── Replies & Optimization ───────────────────────────────────────────────────

class Reply(Base):
    """Incoming prospect reply classified with AI and rule heuristics."""
    __tablename__ = "replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    email_record_id = Column(Integer, ForeignKey("email_records.id", ondelete="SET NULL"), nullable=True)

    reply_body = Column(Text, nullable=False)
    classification = Column(SQLEnum(ReplyClassification), default=ReplyClassification.UNKNOWN, nullable=False)
    confidence_score = Column(Float, nullable=True)

    provider_message_id = Column(String(255), nullable=True, unique=True, index=True)
    provider_thread_id = Column(String(255), nullable=True, index=True)
    received_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    lead = relationship("Lead", back_populates="replies")
    email_record = relationship("EmailRecord", back_populates="replies")


class EmailTemplate(Base):
    """High-performing email patterns for prompt optimization."""
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_pattern = Column(String(500), nullable=False)
    body_pattern = Column(Text, nullable=False)
    email_type = Column(SQLEnum(EmailType), default=EmailType.INITIAL, nullable=False)

    times_used = Column(Integer, default=0, nullable=False)
    reply_count = Column(Integer, default=0, nullable=False)
    performance_score = Column(Float, default=0.0, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class SuppressionEntry(Base):
    """Global or organization-scoped suppression list to prevent sending to opt-outs or bounced addresses."""
    __tablename__ = "suppression_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    reason = Column(SQLEnum(SuppressionReason), default=SuppressionReason.UNSUBSCRIBE, nullable=False)
    source = Column(String(100), default="user_optout", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_org_suppressed_email"),
        Index("ix_suppression_org_email", "organization_id", "email"),
    )


# ── Audit & Observability ────────────────────────────────────────────────────

class AuditLog(Base):
    """Immutable audit trail for sensitive administrative and sending actions."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    action = Column(String(100), nullable=False, index=True)  # user.login, campaign.start, email.sent
    resource_type = Column(String(50), nullable=False)  # campaign, lead, account
    resource_id = Column(String(100), nullable=True)
    details_json = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    # Relationships
    organization = relationship("Organization", back_populates="audit_logs")


# ── Backward-Compatible Aliases ──────────────────────────────────────────────
# Ensure legacy code referencing `GmailAccount` continues to function seamlessly
GmailAccount = EmailProviderAccount
