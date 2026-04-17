"""
Batch Email Sender — Throttled, rate-limited email sending with retry logic.
Enforces daily limits, random delays, and comprehensive error handling.
"""

import logging
import random
import time
from datetime import datetime, timezone

from config.settings import (
    MIN_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    MAX_RETRIES,
    DAILY_SEND_LIMIT,
)
from database.database import get_session
from database.models import (
    EmailRecord, EmailStatus, EmailType, Lead, LeadStatus,
    Campaign, CampaignStatus, GmailAccount,
)
from modules.email_sender.account_manager import AccountManager
from modules.ai_engine.optimizer import record_template

logger = logging.getLogger(__name__)


class BatchSender:
    """
    Manages throttled batch sending of emails with safety guards.
    """

    def __init__(self):
        self.account_manager = AccountManager()
        self._stop_requested = False

    def stop(self):
        """Request the sender to stop after current email."""
        self._stop_requested = True
        logger.info("Batch sender stop requested")

    def send_pending_emails(
        self,
        campaign_id: int = None,
        limit: int = None,
    ) -> dict:
        """
        Send all pending emails with throttling and rate limiting.
        
        Args:
            campaign_id: Optional campaign filter
            limit: Max emails to send in this batch (overrides daily limit)
            
        Returns:
            dict with sending stats
        """
        self._stop_requested = False

        # Determine daily limit
        effective_limit = limit or self._get_effective_daily_limit(campaign_id)

        # Get pending emails
        with get_session() as session:
            query = session.query(EmailRecord).filter(
                EmailRecord.status.in_([EmailStatus.PENDING, EmailStatus.QUEUED])
            )

            if campaign_id:
                query = query.join(Lead).filter(Lead.campaign_id == campaign_id)

            pending = query.order_by(EmailRecord.created_at).limit(effective_limit).all()
            email_ids = [e.id for e in pending]

        if not email_ids:
            logger.info("No pending emails to send")
            return {"sent": 0, "failed": 0, "total": 0, "stopped": False}

        logger.info(f"Starting batch send: {len(email_ids)} emails, limit={effective_limit}")

        sent = 0
        failed = 0
        stopped = False

        for idx, email_id in enumerate(email_ids):
            if self._stop_requested:
                logger.info("Batch send stopped by user")
                stopped = True
                break

            # Check DB state for Pause signal (handles multi-worker concurrency)
            if campaign_id:
                with get_session() as session:
                    camp = session.query(Campaign).get(campaign_id)
                    if camp and camp.status != CampaignStatus.ACTIVE:
                        logger.info("Batch send stopped — campaign is no longer active.")
                        stopped = True
                        break

            # Check if we've hit the daily limit
            if sent >= effective_limit:
                logger.info(f"Daily limit reached ({effective_limit})")
                break

            # Send with retry
            success = self._send_with_retry(email_id)
            if success:
                sent += 1
            else:
                failed += 1

            # Random delay between sends
            if idx < len(email_ids) - 1 and not self._stop_requested:
                delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                logger.debug(f"Waiting {delay:.1f}s before next send...")
                time.sleep(delay)

        # Update campaign stats
        if campaign_id:
            self._update_campaign_stats(campaign_id)

        result = {
            "sent": sent,
            "failed": failed,
            "total": len(email_ids),
            "stopped": stopped,
        }
        logger.info(f"Batch send complete: {result}")
        return result

    def _send_with_retry(self, email_id: int) -> bool:
        """
        Attempt to send a single email with retry logic.
        Returns True if sent successfully.
        """
        with get_session() as session:
            record = session.query(EmailRecord).get(email_id)
            if not record:
                return False

            lead = session.query(Lead).get(record.lead_id)
            if not lead:
                logger.error(f"Lead not found for email record {email_id}")
                record.status = EmailStatus.FAILED
                record.error_message = "Lead not found"
                return False

            # Get available Gmail account
            gmail_client = self.account_manager.get_available_account()
            if not gmail_client:
                logger.error("No available Gmail accounts for sending")
                record.status = EmailStatus.FAILED
                record.error_message = "No available Gmail accounts"
                return False

            account_email = gmail_client.account_email

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    # Send via Gmail API
                    result = gmail_client.send_email(
                        to=lead.email,
                        subject=record.subject,
                        body=record.body,
                        thread_id=record.gmail_thread_id,
                    )

                    # Update record
                    record.status = EmailStatus.SENT
                    record.gmail_account = account_email
                    record.gmail_message_id = result["message_id"]
                    record.gmail_thread_id = result["thread_id"]
                    record.sent_at = datetime.now(timezone.utc)
                    record.error_message = None

                    # Update lead status
                    if record.email_type == EmailType.INITIAL:
                        lead.status = LeadStatus.EMAILED
                    elif record.email_type == EmailType.FOLLOWUP_1:
                        lead.status = LeadStatus.FOLLOWUP_1_SENT
                    elif record.email_type == EmailType.FOLLOWUP_2:
                        lead.status = LeadStatus.FOLLOWUP_2_SENT

                    # Track for optimization
                    record_template(record.subject, record.body, record.email_type)

                    # Update account send count
                    self.account_manager.record_send(account_email)

                    logger.info(
                        f"[{attempt}/{MAX_RETRIES}] Sent {record.email_type.value} "
                        f"to {lead.email} via {account_email}"
                    )
                    return True

                except Exception as e:
                    logger.warning(
                        f"[{attempt}/{MAX_RETRIES}] Send failed for {lead.email}: {e}"
                    )
                    record.retry_count = attempt
                    record.error_message = str(e)

                    if attempt < MAX_RETRIES:
                        # Exponential backoff
                        backoff = 2 ** attempt + random.uniform(0, 1)
                        time.sleep(backoff)

            # All retries exhausted
            record.status = EmailStatus.FAILED
            logger.error(f"All {MAX_RETRIES} retries exhausted for email to {lead.email}")
            return False

    def _get_effective_daily_limit(self, campaign_id: int = None) -> int:
        """
        Calculate the effective daily send limit, accounting for warmup.
        """
        if campaign_id:
            with get_session() as session:
                campaign = session.query(Campaign).get(campaign_id)
                if campaign and campaign.current_daily_limit:
                    return campaign.current_daily_limit

        return DAILY_SEND_LIMIT

    def _update_campaign_stats(self, campaign_id: int):
        """Update denormalized campaign statistics."""
        with get_session() as session:
            campaign = session.query(Campaign).get(campaign_id)
            if not campaign:
                return

            campaign.total_sent = (
                session.query(EmailRecord)
                .join(Lead)
                .filter(
                    Lead.campaign_id == campaign_id,
                    EmailRecord.status == EmailStatus.SENT,
                )
                .count()
            )
            campaign.total_bounces = (
                session.query(EmailRecord)
                .join(Lead)
                .filter(
                    Lead.campaign_id == campaign_id,
                    EmailRecord.status == EmailStatus.BOUNCED,
                )
                .count()
            )

    def send_single(self, email_id: int) -> bool:
        """Send a single email immediately."""
        return self._send_with_retry(email_id)
