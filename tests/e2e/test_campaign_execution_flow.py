"""
End-to-End Integration Test: Complete Campaign Lifecycle.
Verifies:
1. Tenant creates campaign.
2. Ingests CSV leads.
3. Generates personalized cold emails.
4. Starts campaign (enqueues durable SendJobs).
5. CampaignWorker processes queue and delivers via EmailProvider.
6. EmailRecord and Lead status updated to SENT / EMAILED.
7. Re-running worker handles completed jobs idempotently without duplicate sends.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import io
import pytest

from database.models import Lead, LeadStatus, Campaign, EmailRecord, EmailStatus, SendJob, JobStatus
from workers.campaign_worker import CampaignWorker


def test_complete_end_to_end_campaign_lifecycle(client: TestClient, db_session: Session, tenant_a):
    org_id = tenant_a["org"].id
    headers = tenant_a["headers"]

    # 1. Create Campaign
    camp_resp = client.post(
        "/api/campaigns/create",
        json={"name": "E2E Scale Campaign", "daily_limit": 100},
        headers=headers,
    )
    assert camp_resp.status_code == 200
    camp_id = camp_resp.json()["campaign"]["id"]

    # 2. Ingest CSV Leads
    csv_data = (
        "first_name,last_name,email,company_name,website\n"
        "Elena,Rostova,elena@fintech.local,Fintech Global,https://fintech.local\n"
        "Marcus,Vance,marcus@vance.local,Vance Dynamics,https://vance.local\n"
    )
    upload_resp = client.post(
        "/api/leads/upload-csv",
        data={"campaign_id": camp_id},
        files={"file": ("leads.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
        headers=headers,
    )
    assert upload_resp.status_code == 200
    assert upload_resp.json()["imported"] == 2

    # 3. Generate Cold Emails in Batch
    gen_resp = client.post(
        "/api/emails/generate",
        data={"campaign_id": camp_id, "limit": 10},
        headers=headers,
    )
    assert gen_resp.status_code == 200
    assert gen_resp.json()["generated"] == 2

    # Verify EmailRecords created in PENDING status
    pending_emails = db_session.query(EmailRecord).filter_by(campaign_id=camp_id).all()
    assert len(pending_emails) == 2
    for em in pending_emails:
        assert em.status == EmailStatus.PENDING
        assert len(em.subject) > 0
        assert len(em.body) > 0

    # 4. Start Campaign (Enqueues SendJobs)
    start_resp = client.post(
        f"/api/campaigns/{camp_id}/start",
        headers=headers,
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["jobs_enqueued"] == 2

    # Verify SendJobs in QUEUED state
    queued_jobs = db_session.query(SendJob).filter_by(campaign_id=camp_id).all()
    assert len(queued_jobs) == 2
    for job in queued_jobs:
        assert job.status == JobStatus.QUEUED

    # 5. Run CampaignWorker
    worker = CampaignWorker(worker_id="test-e2e-worker")
    processed_1 = worker.process_next_job()
    assert processed_1 is True

    processed_2 = worker.process_next_job()
    assert processed_2 is True

    # Queue should now be empty
    processed_3 = worker.process_next_job()
    assert processed_3 is False

    # 6. Verify Database State
    db_session.expire_all()
    sent_jobs = db_session.query(SendJob).filter_by(campaign_id=camp_id).all()
    for job in sent_jobs:
        assert job.status == JobStatus.SENT

    sent_emails = db_session.query(EmailRecord).filter_by(campaign_id=camp_id).all()
    for email in sent_emails:
        assert email.status == EmailStatus.SENT
        assert email.provider_message_id is not None
        assert email.sent_at is not None

    emailed_leads = db_session.query(Lead).filter_by(campaign_id=camp_id).all()
    for lead in emailed_leads:
        assert lead.status == LeadStatus.EMAILED

    # 7. Test Idempotency: Re-enqueue and process
    for job in sent_jobs:
        job.status = JobStatus.QUEUED
    db_session.commit()

    # Re-running worker must detect email is already sent and not transmit duplicate
    worker.process_next_job()
    db_session.expire_all()
    email_check = db_session.query(EmailRecord).filter_by(campaign_id=camp_id).first()
    assert email_check.status == EmailStatus.SENT
