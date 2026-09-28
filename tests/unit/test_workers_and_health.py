"""
Unit and integration tests for Workers and Health endpoints:
1. API /health/live and /health/ready probes.
2. SendingPolicyEngine with SuppressionEntry table.
3. EnrichmentWorker claiming and processing.
4. MaintenanceWorker lease reaping and rate limit rollover.
"""

import pytest
from datetime import timedelta
from fastapi.testclient import TestClient

from core.queue import DurableQueue
from database.models import (
    Organization, User, Campaign, CampaignStatus, Lead, LeadStatus,
    EmailProviderAccount, SendJob, EnrichmentJob, SuppressionEntry,
    SuppressionReason, JobStatus, utc_now
)
from services.sending_policy import SendingPolicyEngine
from workers.enrichment_worker import EnrichmentWorker
from workers.maintenance_worker import MaintenanceWorker
from main import app


def test_health_live_endpoint():
    """Verify /health/live returns HTTP 200 and alive status."""
    client = TestClient(app)
    resp = client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alive"
    assert "version" in data


def test_health_ready_endpoint(db_session):
    """Verify /health/ready checks database connection."""
    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "connected"


def test_sending_policy_suppression_table_check(db_session, tenant_a):
    """Verify sending policy blocks recipients recorded in the suppression_entries table."""
    engine = SendingPolicyEngine()
    org = tenant_a["org"]

    account = EmailProviderAccount(
        organization_id=org.id,
        account_email="sender@acme.com",
        is_active=True,
        is_healthy=True,
    )
    campaign = Campaign(
        organization_id=org.id,
        name="Q3 Outbound",
        status=CampaignStatus.ACTIVE,
    )
    lead = Lead(
        organization_id=org.id,
        first_name="Jane",
        last_name="Doe",
        email="optout@prospect.com",
        company_name="Prospect Inc",
        status=LeadStatus.NEW,
    )
    db_session.add_all([account, campaign, lead])
    db_session.flush()

    # Prior to suppression, evaluation allows
    decision = engine.evaluate(db_session, account, campaign, lead)
    assert decision.allowed is True

    # Add to suppression list
    suppression = SuppressionEntry(
        organization_id=org.id,
        email="optout@prospect.com",
        reason=SuppressionReason.UNSUBSCRIBE,
        source="user_optout",
    )
    db_session.add(suppression)
    db_session.flush()

    # After suppression, evaluation denies
    decision2 = engine.evaluate(db_session, account, campaign, lead)
    assert decision2.allowed is False
    assert "suppression list" in decision2.reason


def test_enrichment_worker_execution(db_session, tenant_a, monkeypatch):
    """Verify EnrichmentWorker claims job and invokes pipeline."""
    org = tenant_a["org"]
    lead = Lead(
        organization_id=org.id,
        first_name="Tech",
        last_name="Lead",
        email="tech@target.org",
        company_name="Target Org",
        website="https://target.org",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.flush()

    ejob = EnrichmentJob(
        organization_id=org.id,
        lead_id=lead.id,
        target_url="https://target.org",
        status=JobStatus.QUEUED,
    )
    db_session.add(ejob)
    db_session.flush()

    worker = EnrichmentWorker(worker_id="test-enrich-worker")
    # Mock enrich_lead to avoid live HTTP
    monkeypatch.setattr(worker.enricher, "enrich_lead", lambda lid: True)

    processed = worker.process_next_job(session=db_session)
    assert processed is True

    db_session.refresh(ejob)
    assert ejob.status == JobStatus.SENT
    assert ejob.lease_worker_id is None


def test_maintenance_worker_cycle(db_session, tenant_a):
    """Verify MaintenanceWorker reaps expired leases and resets limits."""
    org = tenant_a["org"]
    now = utc_now()
    past = now - timedelta(seconds=120)

    # 1. Setup expired SendJob
    campaign = Campaign(organization_id=org.id, name="Test", status=CampaignStatus.ACTIVE)
    lead = Lead(organization_id=org.id, first_name="A", last_name="B", email="a@b.com", company_name="C")
    db_session.add_all([campaign, lead])
    db_session.flush()

    from database.models import EmailRecord
    email = EmailRecord(
        organization_id=org.id,
        lead_id=lead.id,
        subject="Hi",
        body="Hello",
        idempotency_key="test-key-maintenance",
    )
    db_session.add(email)
    db_session.flush()

    abandoned_job = SendJob(
        organization_id=org.id,
        campaign_id=campaign.id,
        lead_id=lead.id,
        email_record_id=email.id,
        status=JobStatus.PROCESSING,
        idempotency_key="send:test-maintenance",
        lease_worker_id="crashed-worker",
        lease_expires_at=past,
    )
    db_session.add(abandoned_job)

    # 2. Setup account with counters to reset
    account = EmailProviderAccount(
        organization_id=org.id,
        account_email="counter@test.com",
        sends_today=45,
        sends_this_hour=15,
        last_reset_date="2020-01-01",
    )
    db_session.add(account)
    db_session.flush()

    # Run maintenance worker pass
    m_worker = MaintenanceWorker()
    reaped = m_worker.reap_all_expired_leases(db_session)
    assert reaped >= 1

    db_session.refresh(abandoned_job)
    assert abandoned_job.status == JobStatus.QUEUED
    assert abandoned_job.lease_worker_id is None

    m_worker.reset_provider_rate_limits(db_session)
    db_session.refresh(account)
    assert account.sends_today == 0
    assert account.sends_this_hour == 0
