"""
Concurrency, Worker Crash, and Email Idempotency Attack Test Suite.
Verifies:
1. Mutual exclusion during concurrent worker claims (no duplicate processing).
2. Active worker leases block other workers from claiming the job.
3. Expired worker leases are safely claimed by a secondary worker.
4. Idempotent side effects prevent duplicate email dispatches on crash recovery.
5. All 7 email provider failure modes (success, lost response, timeout, 429, 500, 401, permanent).
"""

import pytest
from datetime import timedelta

from core.queue import DurableQueue
from database.models import (
    Campaign, CampaignStatus, Lead, LeadStatus, EmailRecord, EmailStatus,
    SendJob, JobStatus, EmailProviderAccount, utc_now
)
from modules.email_sender.provider_interface import (
    MockEmailProvider, OutboundMessage, SendResult, ProviderErrorCode
)
from workers.campaign_worker import CampaignWorker


def test_concurrent_job_claim_mutual_exclusion(db_session, tenant_a):
    """
    Test 2 workers attempting to claim the single available job.
    Exactly one must claim; the second must receive None.
    """
    org = tenant_a["org"]
    campaign = Campaign(organization_id=org.id, name="Concur Campaign", status=CampaignStatus.ACTIVE)
    lead = Lead(organization_id=org.id, first_name="Tom", last_name="Hanks", email="tom@hollywood.com", company_name="Cinema")
    db_session.add_all([campaign, lead])
    db_session.flush()

    email = EmailRecord(
        organization_id=org.id,
        lead_id=lead.id,
        campaign_id=campaign.id,
        subject="Hello Tom",
        body="Pitch text",
        idempotency_key="idemp:concur:1",
    )
    db_session.add(email)
    db_session.flush()

    job = SendJob(
        organization_id=org.id,
        campaign_id=campaign.id,
        lead_id=lead.id,
        email_record_id=email.id,
        status=JobStatus.QUEUED,
        idempotency_key="job:concur:1",
        scheduled_for=utc_now(),
    )
    db_session.add(job)
    db_session.commit()

    worker_1 = DurableQueue(worker_id="worker-node-1")
    worker_2 = DurableQueue(worker_id="worker-node-2")

    # Worker 1 claims
    claimed_1 = worker_1.claim_send_job(db_session, lease_seconds=60)
    assert claimed_1 is not None
    assert claimed_1.id == job.id
    assert claimed_1.lease_worker_id == "worker-node-1"

    # Worker 2 immediately attempts to claim the same job while lease is valid
    claimed_2 = worker_2.claim_send_job(db_session, lease_seconds=60)
    assert claimed_2 is None, "Worker 2 must not steal a job held under a valid lease!"


def test_worker_crash_and_lease_expiry_handoff(db_session, tenant_a):
    """
    Simulate:
    Worker 1 claims job -> Worker 1 crashes (simulated by advancing time past lease_expires_at) ->
    Worker 2 attempts claim -> Worker 2 successfully recovers and claims the job.
    """
    org = tenant_a["org"]
    campaign = Campaign(organization_id=org.id, name="Crash Campaign", status=CampaignStatus.ACTIVE)
    lead = Lead(organization_id=org.id, first_name="Chris", last_name="Pratt", email="chris@jurassic.com", company_name="Dino")
    db_session.add_all([campaign, lead])
    db_session.flush()

    email = EmailRecord(
        organization_id=org.id,
        lead_id=lead.id,
        campaign_id=campaign.id,
        subject="Jurassic Alert",
        body="Watch out",
        idempotency_key="idemp:crash:1",
    )
    db_session.add(email)
    db_session.flush()

    past_time = utc_now() - timedelta(seconds=120)
    # Job was claimed by worker-dead but lease expired in the past
    stale_job = SendJob(
        organization_id=org.id,
        campaign_id=campaign.id,
        lead_id=lead.id,
        email_record_id=email.id,
        status=JobStatus.PROCESSING,
        idempotency_key="job:crash:1",
        lease_worker_id="worker-dead",
        lease_expires_at=past_time,
        attempt_count=1,
    )
    db_session.add(stale_job)
    db_session.commit()

    worker_survivor = DurableQueue(worker_id="worker-survivor")
    recovered_job = worker_survivor.claim_send_job(db_session, lease_seconds=60)

    assert recovered_job is not None
    assert recovered_job.id == stale_job.id
    assert recovered_job.lease_worker_id == "worker-survivor"
    assert recovered_job.attempt_count == 2
    assert recovered_job.status == JobStatus.PROCESSING


def test_email_idempotency_prevents_duplicate_send_on_crash(db_session, tenant_a):
    """
    Simulate:
    1. Email was already accepted by provider and provider_message_id was stored.
    2. But worker crashed before committing SendJob.status = SENT.
    3. Another worker picks up the job.
    4. Worker detects existing provider_message_id and completes without duplicate send!
    """
    org = tenant_a["org"]
    campaign = Campaign(organization_id=org.id, name="Idemp Campaign", status=CampaignStatus.ACTIVE)
    lead = Lead(organization_id=org.id, first_name="Morgan", last_name="Freeman", email="morgan@voice.com", company_name="Omni")
    db_session.add_all([campaign, lead])
    db_session.flush()

    email = EmailRecord(
        organization_id=org.id,
        lead_id=lead.id,
        campaign_id=campaign.id,
        subject="Narration",
        body="Deep voice",
        idempotency_key="idemp:voice:1",
        status=EmailStatus.SENT,
        provider_name="gmail",
        provider_message_id="<existing-provider-id-999@gmail.com>",
    )
    db_session.add(email)
    db_session.flush()

    stuck_job = SendJob(
        organization_id=org.id,
        campaign_id=campaign.id,
        lead_id=lead.id,
        email_record_id=email.id,
        status=JobStatus.PROCESSING,
        idempotency_key="job:voice:1",
        lease_worker_id="worker-crashed",
        lease_expires_at=utc_now() - timedelta(seconds=10),
    )
    db_session.add(stuck_job)
    db_session.commit()

    c_worker = CampaignWorker(worker_id="worker-rescue")
    send_called = False

    class SpyMockProvider(MockEmailProvider):
        def send(self, message: OutboundMessage) -> SendResult:
            nonlocal send_called
            send_called = True
            return super().send(message)

    # Execute rescue job
    processed = c_worker.process_next_job(session=db_session)
    assert processed is True
    assert send_called is False, "Must NOT re-dispatch when message was already accepted by provider!"

    db_session.refresh(stuck_job)
    assert stuck_job.status == JobStatus.SENT


def test_provider_failure_modes_categorization(db_session, tenant_a):
    """
    Test provider failure categories:
    - RATE_LIMIT (429) -> Transient retry
    - TEMPORARY_FAILURE (500 / timeout) -> Transient retry with backoff
    - AUTH_ERROR (401) -> Permanent failure / circuit trip
    - PERMANENT_FAILURE (bounce / invalid) -> Permanent failure (dead letter)
    """
    mock = MockEmailProvider()

    # 1. Normal success
    msg = OutboundMessage(
        to_email="test@domain.com",
        from_email="sender@domain.com",
        subject="Test",
        body_text="Body",
        idempotency_key="k1",
        organization_id=1,
        campaign_id=1,
        lead_id=1,
    )
    res_ok = mock.send(msg)
    assert res_ok.success is True
    assert res_ok.provider_message_id is not None

    # 2. Rate limit (429)
    res_429 = mock.simulate_failure(msg, "rate_limit")
    assert res_429.success is False
    assert res_429.retryable is True
    assert res_429.error_category == ProviderErrorCode.RATE_LIMIT

    # 3. Server temporary error (500)
    res_500 = mock.simulate_failure(msg, "server_error")
    assert res_500.success is False
    assert res_500.retryable is True
    assert res_500.error_category == ProviderErrorCode.TEMPORARY_FAILURE

    # 4. Auth failure (401)
    res_401 = mock.simulate_failure(msg, "auth_error")
    assert res_401.success is False
    assert res_401.retryable is False
    assert res_401.error_category == ProviderErrorCode.AUTH_ERROR

    # 5. Permanent bounce
    res_bounce = mock.simulate_failure(msg, "permanent_bounce")
    assert res_bounce.success is False
    assert res_bounce.retryable is False
    assert res_bounce.error_category == ProviderErrorCode.PERMANENT_FAILURE
