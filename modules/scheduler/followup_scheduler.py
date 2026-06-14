"""
Follow-Up Scheduler — Manages automated follow-up timing and execution.
Uses APScheduler for background job scheduling.
"""

import logging
from datetime import datetime, timedelta, timezone

from config.settings import FOLLOWUP_1_DAYS, FOLLOWUP_2_DAYS
from database.database import get_session
from database.models import (
    Lead, LeadStatus, EmailRecord, EmailType, EmailStatus,
    Campaign, CampaignStatus,
)
from modules.ai_engine.followup_generator import generate_followup_for_lead

logger = logging.getLogger(__name__)


class FollowUpScheduler:
    """
    Determines which leads need follow-ups and queues them for sending.
    Runs as a scheduled job via APScheduler.
    """

    def check_and_queue_followups(self, campaign_id: int = None) -> dict:
        """
        Check all eligible leads and generate follow-up emails.
        
        Args:
            campaign_id: Optional campaign filter
            
        Returns:
            dict with scheduling stats
        """
        stats = {
            "followup_1_queued": 0,
            "followup_2_queued": 0,
            "skipped": 0,
            "errors": 0,
        }

        # Check if campaign is active
        if campaign_id:
            with get_session() as session:
                campaign = session.get(Campaign, campaign_id)
                if not campaign or campaign.status != CampaignStatus.ACTIVE:
                    logger.info(f"Campaign {campaign_id} not active, skipping follow-ups")
                    return stats

        now = datetime.utcnow()
        followup_1_cutoff = now - timedelta(days=FOLLOWUP_1_DAYS)
        followup_2_cutoff = now - timedelta(days=FOLLOWUP_2_DAYS)

        # ── Follow-Up 1: Leads emailed > 2 days ago without reply ────────
        # Collect eligible lead IDs in a short-lived session, then generate outside
        eligible_lead_ids: list[int] = []
        with get_session() as session:
            query = session.query(Lead).filter(
                Lead.status == LeadStatus.EMAILED,
            )
            if campaign_id:
                query = query.filter(Lead.campaign_id == campaign_id)

            emailed_leads = query.all()

            for lead in emailed_leads:
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

                if initial.sent_at > followup_1_cutoff:
                    stats["skipped"] += 1
                    continue

                existing = (
                    session.query(EmailRecord)
                    .filter_by(lead_id=lead.id, email_type=EmailType.FOLLOWUP_1)
                    .first()
                )
                if existing:
                    stats["skipped"] += 1
                    continue

                eligible_lead_ids.append(lead.id)

        for lead_id in eligible_lead_ids:
            try:
                result = generate_followup_for_lead(lead_id, EmailType.FOLLOWUP_1)
                if result:
                    stats["followup_1_queued"] += 1
                    logger.info(f"Queued follow-up 1 for lead {lead_id}")
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Failed to queue follow-up 1 for lead {lead_id}: {e}")

        # ── Follow-Up 2: Leads with follow-up 1 sent > 3 more days ago ──
        with get_session() as session:
            query = session.query(Lead).filter(
                Lead.status == LeadStatus.FOLLOWUP_1_SENT,
            )
            if campaign_id:
                query = query.filter(Lead.campaign_id == campaign_id)

            followup1_leads = query.all()

            for lead in followup1_leads:
                fu1 = (
                    session.query(EmailRecord)
                    .filter_by(
                        lead_id=lead.id,
                        email_type=EmailType.FOLLOWUP_1,
                        status=EmailStatus.SENT,
                    )
                    .first()
                )
                if not fu1 or not fu1.sent_at:
                    continue

                # Follow-up 2 should be sent FOLLOWUP_2_DAYS after the initial email,
                # but only if enough time has passed since follow-up 1 as well
                if fu1.sent_at > followup_2_cutoff:
                    stats["skipped"] += 1
                    continue

                existing = (
                    session.query(EmailRecord)
                    .filter_by(lead_id=lead.id, email_type=EmailType.FOLLOWUP_2)
                    .first()
                )
                if existing:
                    stats["skipped"] += 1
                    continue

                try:
                    result = generate_followup_for_lead(lead.id, EmailType.FOLLOWUP_2)
                    if result:
                        stats["followup_2_queued"] += 1
                        logger.info(f"Queued follow-up 2 for lead {lead.id}")
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Failed to queue follow-up 2 for lead {lead.id}: {e}")

        logger.info(f"Follow-up check complete: {stats}")
        return stats

    def get_followup_status(self, campaign_id: int = None) -> dict:
        """
        Get current follow-up pipeline status.
        
        Returns:
            dict with counts of leads at each stage
        """
        with get_session() as session:
            query_base = session.query(Lead)
            if campaign_id:
                query_base = query_base.filter(Lead.campaign_id == campaign_id)

            return {
                "awaiting_followup_1": query_base.filter(
                    Lead.status == LeadStatus.EMAILED
                ).count(),
                "followup_1_sent": query_base.filter(
                    Lead.status == LeadStatus.FOLLOWUP_1_SENT
                ).count(),
                "followup_2_sent": query_base.filter(
                    Lead.status == LeadStatus.FOLLOWUP_2_SENT
                ).count(),
                "replied": query_base.filter(
                    Lead.status == LeadStatus.REPLIED
                ).count(),
                "bounced": query_base.filter(
                    Lead.status == LeadStatus.BOUNCED
                ).count(),
                "unsubscribed": query_base.filter(
                    Lead.status == LeadStatus.UNSUBSCRIBED
                ).count(),
            }
