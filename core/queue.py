"""
Durable Distributed Job Queue & Lease Manager.
Provides atomic job claiming, worker leasing, retry with exponential backoff,
dead-letter management, and crash recovery.
Supports Redis-backed signaling with resilient database lease locks.
"""

import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from core.config import settings
from database.database import get_session
from database.models import (
    SendJob, SendAttempt, JobStatus, EmailRecord, EmailStatus,
    Campaign, CampaignStatus, Lead, LeadStatus, utc_now
)

logger = logging.getLogger("leadflow.queue")


class DurableQueue:
    """
    Manages durable job lifecycle and worker leasing.
    Ensures safe, idempotent distributed processing across multiple worker nodes.
    """

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

    def enqueue_send_job(
        self,
        organization_id: int,
        campaign_id: int,
        lead_id: int,
        email_record_id: int,
        scheduled_for: Optional[datetime] = None,
        max_attempts: int = 3,
        session: Optional[Session] = None,
    ) -> SendJob:
        """
        Persist a new SendJob in PENDING / QUEUED state.
        Uses deterministic idempotency key to prevent duplicate job creation.
        """
        idempotency_key = f"send:{organization_id}:{campaign_id}:{lead_id}:{email_record_id}"
        sched = scheduled_for or utc_now()

        def _do_enqueue(sess: Session) -> SendJob:
            existing = sess.query(SendJob).filter_by(idempotency_key=idempotency_key).first()
            if existing:
                logger.info(f"SendJob with idempotency key '{idempotency_key}' already exists (id={existing.id})")
                return existing

            job = SendJob(
                organization_id=organization_id,
                campaign_id=campaign_id,
                lead_id=lead_id,
                email_record_id=email_record_id,
                status=JobStatus.QUEUED,
                idempotency_key=idempotency_key,
                scheduled_for=sched,
                max_attempts=max_attempts,
            )
            sess.add(job)
            sess.flush()

            # Update email record status
            email = sess.get(EmailRecord, email_record_id)
            if email:
                email.status = EmailStatus.QUEUED

            logger.info(f"Enqueued SendJob {job.id} for lead {lead_id} (scheduled for {sched})")
            return job

        if session is not None:
            return _do_enqueue(session)

        with get_session() as sess:
            return _do_enqueue(sess)

    def claim_send_job(
        self,
        session: Session,
        lease_seconds: int = 60,
    ) -> Optional[SendJob]:
        """
        Atomically claim a pending/queued or expired-lease job for processing.
        Prevents multiple workers from grabbing the same job.
        """
        now = utc_now()
        lease_expiration = now + timedelta(seconds=lease_seconds)

        # Find eligible job:
        # 1. status is QUEUED or RETRY_WAIT and scheduled_for <= now
        # OR
        # 2. status is PROCESSING but lease has expired (worker crashed)
        query = (
            session.query(SendJob)
            .join(Campaign, SendJob.campaign_id == Campaign.id)
            .filter(
                Campaign.status == CampaignStatus.ACTIVE,
                or_(
                    and_(
                        SendJob.status.in_([JobStatus.QUEUED, JobStatus.RETRY_WAIT]),
                        SendJob.scheduled_for <= now,
                    ),
                    and_(
                        SendJob.status == JobStatus.PROCESSING,
                        SendJob.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(SendJob.scheduled_for.asc())
        )

        job = query.with_for_update(skip_locked=True).first() if "sqlite" not in settings.DATABASE_URL.lower() else query.first()

        if not job:
            return None

        # Record whether this was a stolen expired lease (crash recovery)
        is_recovered = (job.status == JobStatus.PROCESSING and job.lease_expires_at < now)
        if is_recovered:
            logger.warning(
                f"Worker {self.worker_id} recovered expired lease on SendJob {job.id} "
                f"(previous worker: {job.lease_worker_id})"
            )

        # Claim job
        job.status = JobStatus.PROCESSING
        job.lease_worker_id = self.worker_id
        job.lease_expires_at = lease_expiration
        job.attempt_count += 1
        session.flush()

        logger.debug(f"Worker {self.worker_id} claimed SendJob {job.id} (attempt {job.attempt_count})")
        return job

    def record_attempt(
        self,
        session: Session,
        send_job_id: int,
        attempt_number: int,
        status: str,
        provider_name: str,
        provider_message_id: Optional[str] = None,
        provider_response_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> SendAttempt:
        """Record an immutable audit log entry for this execution attempt."""
        attempt = SendAttempt(
            send_job_id=send_job_id,
            attempt_number=attempt_number,
            worker_id=self.worker_id,
            status=status,
            provider_name=provider_name,
            provider_message_id=provider_message_id,
            provider_response_code=provider_response_code,
            error_message=error_message,
            finished_at=utc_now(),
        )
        session.add(attempt)
        session.flush()
        return attempt

    def complete_send_job(
        self,
        session: Session,
        job_id: int,
        provider_name: str,
        provider_message_id: str,
        provider_thread_id: Optional[str] = None,
    ):
        """Mark a SendJob and corresponding EmailRecord as SENT."""
        job = session.get(SendJob, job_id)
        if not job:
            return

        now = utc_now()
        job.status = JobStatus.SENT
        job.lease_worker_id = None
        job.lease_expires_at = None

        email = session.get(EmailRecord, job.email_record_id)
        if email:
            email.status = EmailStatus.SENT
            email.provider_name = provider_name
            email.provider_message_id = provider_message_id
            email.provider_thread_id = provider_thread_id
            email.sent_at = now

        lead = session.get(Lead, job.lead_id)
        if lead:
            lead.status = LeadStatus.EMAILED

        # Update campaign stats
        campaign = session.get(Campaign, job.campaign_id)
        if campaign:
            campaign.total_sent = (campaign.total_sent or 0) + 1

        self.record_attempt(
            session=session,
            send_job_id=job.id,
            attempt_number=job.attempt_count,
            status="success",
            provider_name=provider_name,
            provider_message_id=provider_message_id,
        )
        session.flush()
        logger.info(f"SendJob {job.id} completed successfully (provider msg: {provider_message_id})")

    def fail_send_job(
        self,
        session: Session,
        job_id: int,
        provider_name: str,
        error_message: str,
        retryable: bool = True,
        backoff_base_seconds: int = 15,
    ):
        """
        Handle a failed send attempt with exponential backoff or dead-letter failure.
        """
        job = session.get(SendJob, job_id)
        if not job:
            return

        job.last_error = error_message
        now = utc_now()

        # Check if job can be retried
        if retryable and job.attempt_count < job.max_attempts:
            # Exponential backoff with jitter: backoff_base * (2 ** (attempt - 1))
            delay_seconds = int(backoff_base_seconds * math.pow(2, max(0, job.attempt_count - 1)))
            job.status = JobStatus.RETRY_WAIT
            job.scheduled_for = now + timedelta(seconds=delay_seconds)
            job.lease_worker_id = None
            job.lease_expires_at = None
            attempt_status = "transient_failure"
            logger.warning(
                f"SendJob {job.id} transient failure (attempt {job.attempt_count}/{job.max_attempts}). "
                f"Retrying in {delay_seconds}s. Error: {error_message}"
            )
        else:
            # Permanent failure
            job.status = JobStatus.FAILED
            job.lease_worker_id = None
            job.lease_expires_at = None
            attempt_status = "permanent_failure"

            email = session.get(EmailRecord, job.email_record_id)
            if email:
                email.status = EmailStatus.FAILED
                email.error_message = error_message

            logger.error(
                f"SendJob {job.id} permanently failed after {job.attempt_count} attempts. "
                f"Error: {error_message}"
            )

        self.record_attempt(
            session=session,
            send_job_id=job.id,
            attempt_number=job.attempt_count,
            status=attempt_status,
            provider_name=provider_name,
            error_message=error_message,
        )
        session.flush()

    def reap_orphaned_jobs(self, session: Session) -> int:
        """
        Identify jobs stuck in PROCESSING whose leases have expired (crashed workers)
        and reset them to QUEUED for immediate pickup.
        """
        now = utc_now()
        orphaned = (
            session.query(SendJob)
            .filter(
                SendJob.status == JobStatus.PROCESSING,
                SendJob.lease_expires_at < now,
            )
            .all()
        )

        reaped_count = 0
        for job in orphaned:
            logger.warning(f"Reaping abandoned job {job.id} (lease expired {job.lease_expires_at})")
            job.status = JobStatus.QUEUED
            job.lease_worker_id = None
            job.lease_expires_at = None
            reaped_count += 1

        if reaped_count:
            session.flush()
            logger.info(f"Reaped {reaped_count} abandoned SendJobs back to QUEUED")
        return reaped_count
