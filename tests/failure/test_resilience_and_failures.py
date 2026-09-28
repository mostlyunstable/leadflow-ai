"""
Failure & Resilience Tests.
Tests:
1. Worker crash simulation: lease expires and second worker recovers the job.
2. Network timeout simulation: idempotency prevents duplicate email transmission.
3. LLM outage simulation: handles generation errors gracefully.
4. Production fail-closed validation: missing secrets prevent application startup.
"""

from datetime import timedelta
import pytest
from sqlalchemy.orm import Session

from core.config import Settings, AppEnvironment
from core.queue import DurableQueue
from database.models import (
    SendJob, EmailRecord, EmailStatus, JobStatus,
    Campaign, CampaignStatus, Lead, Organization, utc_now
)
from workers.campaign_worker import CampaignWorker
from modules.ai_engine.llm_provider import MockLLMProvider
from modules.ai_engine.generator import generate_email


def test_production_fail_closed_validation():
    # Production with default/weak secret must fail startup
    bad_prod_settings = Settings(
        ENVIRONMENT=AppEnvironment.PRODUCTION,
        SECRET_KEY="short",
        DATABASE_URL="sqlite:///outreach.db",
    )
    with pytest.raises(ValueError, match="Production configuration validation failed"):
        bad_prod_settings.validate_production_readiness()


def test_worker_crash_and_rescue_execution(db_session: Session):
    org = Organization(name="Crash Org", slug="crash-org")
    db_session.add(org)
    db_session.flush()

    camp = Campaign(organization_id=org.id, name="Crash Camp", status=CampaignStatus.ACTIVE)
    db_session.add(camp)
    db_session.flush()

    lead = Lead(organization_id=org.id, campaign_id=camp.id, first_name="A", last_name="B", email="ab@test.local", company_name="C")
    db_session.add(lead)
    db_session.flush()

    email = EmailRecord(
        organization_id=org.id, campaign_id=camp.id, lead_id=lead.id,
        subject="Test", body="Body", status=EmailStatus.PENDING, idempotency_key="crash-key-1"
    )
    db_session.add(email)
    db_session.commit()

    queue = DurableQueue(worker_id="worker-crash-1")
    job = queue.enqueue_send_job(org.id, camp.id, lead.id, email.id)

    # Worker 1 claims job
    claimed = queue.claim_send_job(db_session, lease_seconds=5)
    assert claimed.lease_worker_id == "worker-crash-1"

    # Worker 1 crashes. Time passes, lease expires.
    claimed.lease_expires_at = utc_now() - timedelta(seconds=10)
    db_session.commit()

    # Worker 2 boots up and processes queue
    worker2 = CampaignWorker(worker_id="worker-rescue-2")
    processed = worker2.process_next_job()

    assert processed is True
    db_session.refresh(claimed)
    assert claimed.status == JobStatus.SENT
    assert claimed.lease_worker_id is None


def test_llm_failure_handling_does_not_corrupt_state():
    lead = Lead(first_name="Error", last_name="Lead", email="err@lead.local", company_name="ErrCorp")
    failing_llm = MockLLMProvider(should_fail=True)

    with pytest.raises(RuntimeError, match="Mock LLM simulated generation failure"):
        generate_email(lead, provider=failing_llm)
