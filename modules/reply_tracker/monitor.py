"""
Inbox Monitor — Polls Gmail inboxes for replies to sent emails.
Matches replies to sent emails via thread_id, detects bounces.
"""

import logging
from datetime import datetime, timezone

from database.database import get_session
from database.models import (
    EmailRecord, EmailStatus, Lead, LeadStatus, Reply,
    GmailAccount, ReplyClassification,
)
from modules.email_sender.gmail_client import GmailClient
from modules.reply_tracker.classifier import classify_reply
from modules.ai_engine.optimizer import record_reply

logger = logging.getLogger(__name__)

# Bounce indicator strings in sender/subject
BOUNCE_INDICATORS = [
    "mailer-daemon",
    "mail delivery subsystem",
    "delivery status notification",
    "undeliverable",
    "delivery failure",
    "returned mail",
    "mail delivery failed",
    "message not delivered",
]


class InboxMonitor:
    """
    Monitors Gmail inboxes for replies to sent outreach emails.
    Classifies replies and updates lead statuses accordingly.
    """

    def __init__(self):
        self._clients: dict[str, GmailClient] = {}

    def _get_client(self, account_email: str) -> GmailClient:
        """Get or create a Gmail client for an account."""
        if account_email not in self._clients:
            client = GmailClient(account_email)
            client.authenticate()
            self._clients[account_email] = client
        return self._clients[account_email]

    def check_all_accounts(self) -> dict:
        """
        Check all active Gmail accounts for new replies.
        
        Returns:
            dict with check stats
        """
        stats = {"accounts_checked": 0, "new_replies": 0, "bounces": 0, "errors": 0}

        with get_session() as session:
            accounts = (
                session.query(GmailAccount)
                .filter_by(is_active=True, is_healthy=True)
                .all()
            )
            account_emails = [a.email for a in accounts]

        for account_email in account_emails:
            try:
                result = self.check_account(account_email)
                stats["accounts_checked"] += 1
                stats["new_replies"] += result["new_replies"]
                stats["bounces"] += result["bounces"]
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error checking {account_email}: {e}")

        logger.info(f"Inbox check complete: {stats}")
        return stats

    def check_account(self, account_email: str) -> dict:
        """
        Check a single Gmail account for new replies.
        
        Returns:
            dict with new_replies, bounces counts
        """
        client = self._get_client(account_email)
        result = {"new_replies": 0, "bounces": 0}

        # Get all thread IDs we've sent to from this account
        with get_session() as session:
            sent_records = (
                session.query(EmailRecord)
                .filter(
                    EmailRecord.gmail_account == account_email,
                    EmailRecord.status == EmailStatus.SENT,
                    EmailRecord.gmail_thread_id.isnot(None),
                )
                .all()
            )

            # Map thread_id → email_record for quick lookup
            thread_map = {}
            for record in sent_records:
                if record.gmail_thread_id not in thread_map:
                    thread_map[record.gmail_thread_id] = record

        if not thread_map:
            return result

        # Fetch recent inbox messages
        messages = client.get_messages(
            query="is:inbox newer_than:7d",
            max_results=100,
        )

        for msg_meta in messages:
            msg_id = msg_meta["id"]

            # Check if we already processed this message
            with get_session() as session:
                existing_reply = (
                    session.query(Reply)
                    .filter_by(gmail_message_id=msg_id)
                    .first()
                )
                if existing_reply:
                    continue

            # Get full message details
            detail = client.get_message_detail(msg_id)
            if not detail:
                continue

            thread_id = detail.get("thread_id")
            if thread_id not in thread_map:
                continue

            # This is a reply to one of our sent emails
            sender = detail.get("from", "").lower()
            subject = detail.get("subject", "").lower()
            body = detail.get("body", "")

            # Check if it's a bounce
            is_bounce = any(
                indicator in sender or indicator in subject
                for indicator in BOUNCE_INDICATORS
            )

            with get_session() as session:
                email_record = (
                    session.query(EmailRecord)
                    .filter_by(gmail_thread_id=thread_id, status=EmailStatus.SENT)
                    .first()
                )
                if not email_record:
                    continue

                lead = session.query(Lead).get(email_record.lead_id)
                if not lead:
                    continue

                if is_bounce:
                    # Handle bounce
                    email_record.status = EmailStatus.BOUNCED
                    lead.status = LeadStatus.BOUNCED
                    result["bounces"] += 1
                    logger.info(f"Bounce detected for {lead.email}")
                else:
                    # Classify the reply
                    classification, confidence = classify_reply(body)

                    # Create reply record
                    reply = Reply(
                        lead_id=lead.id,
                        email_record_id=email_record.id,
                        reply_body=body,
                        classification=classification,
                        confidence_score=confidence,
                        gmail_message_id=msg_id,
                        gmail_thread_id=thread_id,
                        received_at=datetime.now(timezone.utc),
                    )
                    session.add(reply)

                    # Update lead status
                    if classification == ReplyClassification.UNSUBSCRIBE:
                        lead.status = LeadStatus.UNSUBSCRIBED
                    else:
                        lead.status = LeadStatus.REPLIED

                    # Record for optimization
                    record_reply(email_record.id)

                    result["new_replies"] += 1
                    logger.info(
                        f"Reply from {lead.email}: {classification.value} "
                        f"(confidence: {confidence:.2f})"
                    )

                    # Mark as read
                    client.mark_as_read(msg_id)

        return result
