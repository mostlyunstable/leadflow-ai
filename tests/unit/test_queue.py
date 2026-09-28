"""
Unit Tests for Durable Distributed Queue & State Machine.
Tests:
1. Enqueueing with deterministic idempotency keys.
2. Atomic worker claiming and lease expiration.
3. Exponential backoff retry policy.
4. Dead-letter permanent failure handling.
5. Orphaned lease recovery (worker crash recovery).
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
import pytest

from core.queue import DurableQueue
from database.models import (
    SendJob, EmailRecord, EmailStatus, JobStatus,
    Campaign, CampaignStatus, Lead, LeadStatus, Organization, utc_now
)


def _seed_test_campaign(db_session: Session):
    org = Organization(name="Test Org", slug="test-org")
    db_session.add(org)
    db_session.flush()

    camp = Campaign(organization_id=org.id, name="Test Campaign", status=CampaignStatus.ACTIVE)
    db_session.add(camp)
    db_session.flush()

    lead = Lead(
        organization_id=org.id,
        campaign_id=camp.id,
        first_name="John",
        last_name="Doe",
        email="john@example.com",
        company_name="Example Inc",
    )
    db_session.add(lead)
    db_session.flush()

    email = EmailRecord(
        organization_id=org.id,
        campaign_id=camp.id,
        lead_id=lead.id,
        subject="Hello",
        body="World",
        status=EmailStatus.PENDING,
        idempotency_key="email-key-1",
    )
    db_session.add(email)
    db_session.commit()

    return org, camp, lead, email


def test_enqueue_send_job_idempotency(db_session: Session):
    org, camp, lead, email = _seed_test_campaign(db_session)
    queue = DurableQueue(worker_id="worker-1")

    # Enqueue first time
    job1 = queue.enqueue_send_job(
        organization_id=org.id,
        campaign_id=camp.id,
        lead_id=lead.id,
        email_record_id=email.id,
    )
    assert job1.id is not None
    assert job1.status == JobStatus.QUEUED

    # Duplicate enqueue with same parameters should return existing job without creating duplicate
    job2 = queue.enqueue_send_job(
        organization_id=org.id,
        campaign_id=camp.id,
        lead_id=lead.id,
        email_record_id=email.id,
    )
    assert job2.id == job1.id

    # Verify total count in DB
    total = db_session.query(SendJob).count()
    assert total == 1


def test_worker_claim_and_complete(db_session: Session):
    org, camp, lead, email = _seed_test_campaign(db_session)
    queue = DurableQueue(worker_id="worker-1")

    queue.enqueue_send_job(org.id, camp.id, lead.id, email.id)

    # Worker 1 claims job
    claimed = queue.claim_send_job(db_session, lease_seconds=60)
    assert claimed is not None
    assert claimed.status == JobStatus.PROCESSING
    assert claimed.lease_worker_id == "worker-1"
    assert claimed.attempt_count == 1

    # Worker 2 tries to claim while lease is active
    queue2 = DurableQueue(worker_id="worker-2")
    claimed2 = queue2.claim_send_job(db_session, lease_seconds=60)
    assert claimed2 is None  # Locked by worker 1

    # Complete job
    queue.complete_send_job(
        session=db_session,
        job_id=claimed.id,
        provider_name="mock",
        provider_message_id="mock-123",
    )

    db_session.refresh(claimed)
    db_session.refresh(email)
    assert claimed.status == JobStatus.SENT
    assert email.status == EmailStatus.SENT
    assert email.provider_message_id == "mock-123"


def test_exponential_backoff_and_permanent_failure(db_session: Session):
    org, camp, lead, email = _seed_test_campaign(db_session)
    queue = DurableQueue(worker_id="worker-1")

    job = queue.enqueue_send_job(org.id, camp.id, lead.id, email.id, max_attempts=2)
    claimed = queue.claim_send_job(db_session)

    # First transient failure -> should enter RETRY_WAIT
    queue.fail_send_job(
        session=db_session,
        job_id=claimed.id,
        provider_name="mock",
        error_message="Simulated 429 Rate Limit",
        retryable=True,
    )
    db_session.refresh(claimed)
    assert claimed.status == JobStatus.RETRY_WAIT
    assert claimed.attempt_count == 1
    sched = claimed.scheduled_for
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    assert sched > utc_now()

    # Fast-forward time for retry
    claimed.scheduled_for = utc_now() - timedelta(seconds=1)
    db_session.commit()

    # Second claim
    claimed_retry = queue.claim_send_job(db_session)
    assert claimed_retry is not None
    assert claimed_retry.attempt_count == 2

    # Second failure on max_attempts=2 -> should permanently fail
    queue.fail_send_job(
        session=db_session,
        job_id=claimed_retry.id,
        provider_name="mock",
        error_message="Repeated 429",
        retryable=True,
    )
    db_session.refresh(claimed_retry)
    assert claimed_retry.status == JobStatus.FAILED


def test_worker_crash_and_lease_recovery(db_session: Session):
    org, camp, lead, email = _seed_test_campaign(db_session)
    crashed_worker = DurableQueue(worker_id="worker-crashed")

    crashed_worker.enqueue_send_job(org.id, camp.id, lead.id, email.id)
    job = crashed_worker.claim_send_job(db_session, lease_seconds=10)

    # Simulate worker crash: lease expires in the past
    job.lease_expires_at = utc_now() - timedelta(seconds=5)
    db_session.commit()

    # Rescuing worker should reap or reclaim the expired job
    rescuing_worker = DurableQueue(worker_id="worker-rescue")
    claimed_rescue = rescuing_worker.claim_send_job(db_session, lease_seconds=60)

    assert claimed_rescue is not None
    assert claimed_rescue.id == job.id
    assert claimed_rescue.lease_worker_id == "worker-rescue"
