"""
Follow-Up Scheduler — Manages automated follow-up timing and queueing.
Enforces timezone-aware UTC datetime comparisons and multi-tenant scoping.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from core.config import settings
from core.queue import DurableQueue
from database.database import get_session
from database.models import (
    Lead, LeadStatus, EmailRecord, EmailType, EmailStatus,
    Campaign, CampaignStatus, utc_now
)
from modules.ai_engine.followup_generator import generate_followup_for_lead

logger = logging.getLogger("leadflow.scheduler.followup")


class FollowUpScheduler:
    """
    Identifies leads eligible for follow-ups and creates durable jobs in the queue.
    """

    def __init__(self):
        self.queue = DurableQueue()

    def check_and_queue_followups(self, campaign_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Check all eligible leads and queue follow-up emails safely with durable jobs.
        """
        stats = {
            "followup_1_queued": 0,
            "followup_2_queued": 0,
            "skipped": 0,
            "errors": 0,
        }

        now = utc_now()
        followup_1_cutoff = now - timedelta(days=settings.FOLLOWUP_1_DAYS)
        followup_2_cutoff = now - timedelta(days=settings.FOLLOWUP_2_DAYS)

        # ── Follow-Up 1: Leads emailed >= 2 days ago without reply ────────
        with get_session() as session:
            query = session.query(Lead).filter(
                Lead.status == LeadStatus.EMAILED,
            )
            if campaign_id:
                query = query.filter(Lead.campaign_id == campaign_id)

            leads_f1 = query.all()
            target_f1 = []
            for lead in leads_f1:
                initial = (
                    session.query(EmailRecord)
                    .filter_by(
                        lead_id=lead.id,
                        email_type=EmailType.INITIAL,
                        status=EmailStatus.SENT,
                    )
                    .first()
                )
                if not initial or not initial.sent_at:
                    continue

                sent_at = initial.sent_at
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)

                if sent_at <= followup_1_cutoff:
                    target_f1.append((lead.id, lead.organization_id, lead.campaign_id))

        for lead_id, org_id, camp_id in target_f1:
            try:
                res = generate_followup_for_lead(lead_id, EmailType.FOLLOWUP_1)
                if res:
                    self.queue.enqueue_send_job(
                        organization_id=org_id,
                        campaign_id=camp_id,
                        lead_id=lead_id,
                        email_record_id=res["record_id"],
                    )
                    stats["followup_1_queued"] += 1
            except Exception as e:
                logger.error(f"Error queueing Follow-up 1 for lead {lead_id}: {e}")
                stats["errors"] += 1

        # ── Follow-Up 2: Leads sent Follow-Up 1 >= 5 days ago without reply ─
        with get_session() as session:
            query_f2 = session.query(Lead).filter(
                Lead.status == LeadStatus.FOLLOWUP_1_SENT,
            )
            if campaign_id:
                query_f2 = query_f2.filter(Lead.campaign_id == campaign_id)

            leads_f2 = query_f2.all()
            target_f2 = []
            for lead in leads_f2:
                f1_email = (
                    session.query(EmailRecord)
                    .filter_by(
                        lead_id=lead.id,
                        email_type=EmailType.FOLLOWUP_1,
                        status=EmailStatus.SENT,
                    )
                    .first()
                )
                if not f1_email or not f1_email.sent_at:
                    continue

                sent_at = f1_email.sent_at
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)

                if sent_at <= followup_2_cutoff:
                    target_f2.append((lead.id, lead.organization_id, lead.campaign_id))

        for lead_id, org_id, camp_id in target_f2:
            try:
                res = generate_followup_for_lead(lead_id, EmailType.FOLLOWUP_2)
                if res:
                    self.queue.enqueue_send_job(
                        organization_id=org_id,
                        campaign_id=camp_id,
                        lead_id=lead_id,
                        email_record_id=res["record_id"],
                    )
                    stats["followup_2_queued"] += 1
            except Exception as e:
                logger.error(f"Error queueing Follow-up 2 for lead {lead_id}: {e}")
                stats["errors"] += 1

        logger.info(f"Follow-up scheduling run complete: {stats}")
        return stats
