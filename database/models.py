"""
Database Models — SQLAlchemy ORM definitions for the outreach system.
All tables: leads, email_records, replies, campaigns, email_templates, gmail_accounts.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, Enum as SQLEnum, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship, DeclarativeBase
import enum


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


# ── Enums ────────────────────────────────────────────────────────────────────

class LeadStatus(str, enum.Enum):
    NEW = "new"
    ENRICHED = "enriched"
    EMAIL_GENERATED = "email_generated"
    EMAILED = "emailed"
    FOLLOWUP_1_SENT = "followup_1_sent"
    FOLLOWUP_2_SENT = "followup_2_sent"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"


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


class ReplyClassification(str, enum.Enum):
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    SPAM = "spam"
    UNKNOWN = "unknown"


class CampaignStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


# ── Models ───────────────────────────────────────────────────────────────────

class Lead(Base):
    """A lead/prospect to reach out to."""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    company_name = Column(String(255), nullable=False)
    website = Column(String(500), nullable=True)
    industry = Column(String(200), nullable=True)

    # Enrichment fields
    company_description = Column(Text, nullable=True)
    key_offering = Column(Text, nullable=True)
    enriched = Column(Boolean, default=False)

    # Status tracking
    status = Column(
        SQLEnum(LeadStatus),
        default=LeadStatus.NEW,
        nullable=False,
        index=True,
    )
    source = Column(String(50), default="csv")  # csv, sheets
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    emails = relationship("EmailRecord", back_populates="lead", cascade="all, delete-orphan")
    replies = relationship("Reply", back_populates="lead", cascade="all, delete-orphan")
    campaign = relationship("Campaign", back_populates="leads")

    __table_args__ = (
        Index("ix_leads_status_campaign", "status", "campaign_id"),
        Index("ix_leads_campaign_id", "campaign_id"),
    )

    def __repr__(self):
        return f"<Lead {self.first_name} {self.last_name} ({self.email})>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class EmailRecord(Base):
    """Record of every email sent."""
    __tablename__ = "email_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)

    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    email_type = Column(SQLEnum(EmailType), nullable=False)
    status = Column(
        SQLEnum(EmailStatus),
        default=EmailStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Gmail tracking
    gmail_account = Column(String(255), nullable=True)
    gmail_message_id = Column(String(255), nullable=True, unique=True)
    gmail_thread_id = Column(String(255), nullable=True, index=True)

    # Retry tracking
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    # Timestamps
    scheduled_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_email_records_lead_type", "lead_id", "email_type"),
    )

    # Relationships
    lead = relationship("Lead", back_populates="emails")
    replies = relationship("Reply", back_populates="email_record", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<EmailRecord {self.email_type.value} to lead_id={self.lead_id} [{self.status.value}]>"


class Reply(Base):
    """Tracked reply from a lead."""
    __tablename__ = "replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    email_record_id = Column(Integer, ForeignKey("email_records.id"), nullable=True)

    reply_body = Column(Text, nullable=False)
    classification = Column(
        SQLEnum(ReplyClassification),
        default=ReplyClassification.UNKNOWN,
        nullable=False,
    )
    confidence_score = Column(Float, nullable=True)

    # Gmail tracking
    gmail_message_id = Column(String(255), nullable=True, unique=True)
    gmail_thread_id = Column(String(255), nullable=True)

    # Timestamps
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    lead = relationship("Lead", back_populates="replies")
    email_record = relationship("EmailRecord", back_populates="replies")

    def __repr__(self):
        return f"<Reply from lead_id={self.lead_id} [{self.classification.value}]>"


class Campaign(Base):
    """A campaign groups leads and tracks global settings."""
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    status = Column(
        SQLEnum(CampaignStatus),
        default=CampaignStatus.PAUSED,
        nullable=False,
    )
    daily_limit = Column(Integer, default=50)

    # Warmup tracking
    warmup_day = Column(Integer, default=0)
    current_daily_limit = Column(Integer, default=10)

    # Stats (denormalized for fast dashboard reads)
    total_leads = Column(Integer, default=0)
    total_sent = Column(Integer, default=0)
    total_replies = Column(Integer, default=0)
    total_bounces = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)

    # Relationships
    leads = relationship("Lead", back_populates="campaign")

    def __repr__(self):
        return f"<Campaign '{self.name}' [{self.status.value}]>"

    @property
    def reply_rate(self):
        if self.total_sent == 0:
            return 0.0
        return round((self.total_replies / self.total_sent) * 100, 1)

    @property
    def bounce_rate(self):
        if self.total_sent == 0:
            return 0.0
        return round((self.total_bounces / self.total_sent) * 100, 1)


class EmailTemplate(Base):
    """Stores high-performing email variations for optimization."""
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_pattern = Column(String(500), nullable=False)
    body_pattern = Column(Text, nullable=False)
    email_type = Column(SQLEnum(EmailType), default=EmailType.INITIAL)

    # Performance tracking
    times_used = Column(Integer, default=0)
    reply_count = Column(Integer, default=0)
    performance_score = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<EmailTemplate id={self.id} score={self.performance_score}>"

    @property
    def reply_rate(self):
        if self.times_used == 0:
            return 0.0
        return round((self.reply_count / self.times_used) * 100, 1)


class GmailAccount(Base):
    """Registered Gmail account for sending."""
    __tablename__ = "gmail_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    display_name = Column(String(255), nullable=True)
    token_file = Column(String(500), nullable=True)

    # Daily tracking
    sends_today = Column(Integer, default=0)
    last_send_at = Column(DateTime, nullable=True)
    last_reset_date = Column(String(10), nullable=True)  # YYYY-MM-DD

    # Status
    is_active = Column(Boolean, default=True)
    is_healthy = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<GmailAccount {self.email} [{'active' if self.is_active else 'inactive'}]>"
