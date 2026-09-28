"""
Durable Campaign Worker.
Decoupled background worker that consumes SendJobs from the durable queue,
evaluates sending policies, dispatches through EmailProvider abstractions,
and records immutable audit attempts with idempotency guarantees.
Designed to run safely in separate OS processes and survive crashes/restarts.
"""

import logging
import signal
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from typing import Optional
from sqlalchemy.orm import Session

from core.config import settings
from core.queue import DurableQueue
from core.security import decrypt_secret
from database.database import get_session
from database.models import (
    SendJob, EmailRecord, EmailProviderAccount, Campaign, Lead,
    JobStatus, EmailStatus, CampaignStatus, utc_now
)
from modules.email_sender.provider_interface import (
    OutboundMessage, SendResult, EmailProvider, GmailProvider, MockEmailProvider
)
from services.sending_policy import SendingPolicyEngine, PolicyDecision

logger = logging.getLogger("leadflow.worker.campaign")


class CampaignWorker:
    """
    Consumes and processes durable SendJobs.
    """

    def __init__(self, worker_id: Optional[str] = None):
        self.queue = DurableQueue(worker_id=worker_id)
        self.policy_engine = SendingPolicyEngine()
        self.worker_id = self.queue.worker_id
        self._stop_requested = False
        self._setup_signals()

    def _setup_signals(self):
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, AttributeError):
            pass

    def _handle_signal(self, signum, frame):
        logger.info(f"Worker {self.worker_id} received stop signal ({signum}). Finishing current job...")
        self._stop_requested = True

    def process_next_job(self, session: Optional[Session] = None) -> bool:
        """
        Claim and execute a single job from the queue.
        Returns True if a job was claimed and processed, False if queue was empty.
        """
        if session is not None:
            return self._execute_job(session)

        with get_session() as sess:
            return self._execute_job(sess)

    def _execute_job(self, session: Session) -> bool:
        # 1. Reap any abandoned jobs from previously crashed workers
        self.queue.reap_orphaned_jobs(session)

        # 2. Claim next available job
        job = self.queue.claim_send_job(session, lease_seconds=settings.JOB_LEASE_SECONDS)
        if not job:
            return False

        job_id = job.id
        org_id = job.organization_id
        lead_id = job.lead_id
        campaign_id = job.campaign_id
        email_record_id = job.email_record_id
        idempotency_key = job.idempotency_key

        email_rec = session.get(EmailRecord, email_record_id)
        lead = session.get(Lead, lead_id)
        campaign = session.get(Campaign, campaign_id)

        if not email_rec or not lead or not campaign:
            self.queue.fail_send_job(
                session=session,
                job_id=job_id,
                provider_name="system",
                error_message="Referenced lead, email record, or campaign missing",
                retryable=False,
            )
            return True

        # 3. Select an active email provider account
        account = (
            session.query(EmailProviderAccount)
            .filter(
                EmailProviderAccount.organization_id == org_id,
                EmailProviderAccount.is_active == True,
                EmailProviderAccount.is_healthy == True,
            )
            .first()
        )

        # Fallback to mock account if testing or none configured
        provider: EmailProvider
        if not account or not account.encrypted_credentials:
            if settings.ENVIRONMENT == "production":
                self.queue.fail_send_job(
                    session=session,
                    job_id=job_id,
                    provider_name="system",
                    error_message="No configured and active sender accounts available",
                    retryable=True,
                )
                return True
            else:
                # Dev / Test fallback to Mock Provider
                provider = MockEmailProvider()
                sender_email = "mock-sender@leadflow.local"
        else:
            try:
                decrypted_creds = decrypt_secret(account.encrypted_credentials)
                provider = GmailProvider(account.account_email, decrypted_creds)
                sender_email = account.account_email
            except Exception as e:
                self.queue.fail_send_job(
                    session=session,
                    job_id=job_id,
                    provider_name="gmail",
                    error_message=f"Failed to decrypt credentials: {e}",
                    retryable=False,
                )
                return True

        # 4. Evaluate sending policy
        if account:
            decision: PolicyDecision = self.policy_engine.evaluate(
                session=session,
                account=account,
                campaign=campaign,
                lead=lead,
            )

            if not decision.allowed:
                if decision.circuit_broken:
                    campaign.status = CampaignStatus.PAUSED
                    logger.critical(f"Campaign {campaign.id} automatically paused: {decision.reason}")

                if decision.suggested_delay_seconds > 0:
                    from datetime import timedelta
                    job.status = JobStatus.QUEUED
                    job.scheduled_for = utc_now() + timedelta(seconds=decision.suggested_delay_seconds)
                    job.lease_worker_id = None
                    job.lease_expires_at = None
                    logger.info(
                        f"SendJob {job.id} postponed by policy ({decision.reason}). "
                        f"Rescheduled in {decision.suggested_delay_seconds}s"
                    )
                else:
                    self.queue.fail_send_job(
                        session=session,
                        job_id=job.id,
                        provider_name=provider.provider_name,
                        error_message=f"Policy rejection: {decision.reason}",
                        retryable=False,
                    )
                return True

        # 5. Check Idempotency: Has this message already been transmitted?
        if email_rec.status == EmailStatus.SENT and email_rec.provider_message_id:
            logger.warning(
                f"Idempotency hit: EmailRecord {email_rec.id} already has provider_message_id "
                f"'{email_rec.provider_message_id}'. Marking job complete without resending."
            )
            self.queue.complete_send_job(
                session=session,
                job_id=job.id,
                provider_name=email_rec.provider_name or "cached",
                provider_message_id=email_rec.provider_message_id,
                provider_thread_id=email_rec.provider_thread_id,
            )
            return True

        # 6. Dispatch message
        outbound = OutboundMessage(
            to_email=lead.email,
            from_email=sender_email,
            subject=email_rec.subject,
            body_text=email_rec.body,
            idempotency_key=idempotency_key,
            thread_id=email_rec.provider_thread_id,
            organization_id=org_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
        )

        result: SendResult = provider.send(outbound)

        # 7. Persist result
        if result.success and result.provider_message_id:
            self.queue.complete_send_job(
                session=session,
                job_id=job.id,
                provider_name=provider.provider_name,
                provider_message_id=result.provider_message_id,
                provider_thread_id=result.provider_thread_id,
            )
            if account:
                self.policy_engine.record_send(session, account)
        else:
            self.queue.fail_send_job(
                session=session,
                job_id=job.id,
                provider_name=provider.provider_name,
                error_message=result.error_message or "Unknown provider failure",
                retryable=result.retryable,
            )

        return True

    def run_worker_loop(self, poll_interval: float = 1.0):
        """Continuous execution loop for worker process."""
        logger.info(f"Starting CampaignWorker {self.worker_id}...")
        while not self._stop_requested:
            try:
                processed = self.process_next_job()
                if not processed:
                    time.sleep(poll_interval)
            except Exception as e:
                logger.error(f"Worker {self.worker_id} loop encountered unexpected error: {e}", exc_info=True)
                time.sleep(poll_interval * 2)

        logger.info(f"CampaignWorker {self.worker_id} shut down gracefully.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-8s │ %(name)-25s │ %(message)s",
    )
    worker = CampaignWorker()
    worker.run_worker_loop()
