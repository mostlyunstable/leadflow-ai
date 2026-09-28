"""
API Tests for Campaigns, Leads CSV Upload, and Domain Health.
Tests:
1. Campaign creation and listing.
2. Starting campaign enqueues durable SendJobs.
3. Pausing an active campaign.
4. CSV Lead Upload endpoint.
5. Domain DNS Deliverability Diagnostic endpoint.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import io

from database.models import Campaign, CampaignStatus, EmailRecord, EmailStatus, SendJob


def test_create_and_list_campaigns(client: TestClient, tenant_a):
    # Create campaign
    create_resp = client.post(
        "/api/campaigns/create",
        json={"name": "Q4 Outreach", "daily_limit": 75},
        headers=tenant_a["headers"],
    )
    assert create_resp.status_code == 200
    camp_data = create_resp.json()["campaign"]
    assert camp_data["name"] == "Q4 Outreach"
    assert camp_data["daily_limit"] == 75

    # List campaigns
    list_resp = client.get("/api/campaigns", headers=tenant_a["headers"])
    assert list_resp.status_code == 200
    campaigns = list_resp.json()["campaigns"]
    assert any(c["id"] == camp_data["id"] for c in campaigns)


def test_start_campaign_enqueues_durable_jobs(client: TestClient, db_session: Session, tenant_a):
    # Create campaign
    camp = Campaign(
        organization_id=tenant_a["org"].id,
        name="Automated Campaign",
        status=CampaignStatus.DRAFT,
    )
    db_session.add(camp)
    db_session.flush()

    # Seed lead & generated email
    from database.models import Lead, LeadStatus
    lead = Lead(
        organization_id=tenant_a["org"].id,
        campaign_id=camp.id,
        first_name="Sam",
        last_name="Alt",
        email="sam@openai.local",
        company_name="OpenAI",
        status=LeadStatus.EMAIL_GENERATED,
    )
    db_session.add(lead)
    db_session.flush()

    email = EmailRecord(
        organization_id=tenant_a["org"].id,
        campaign_id=camp.id,
        lead_id=lead.id,
        subject="AI Outreach",
        body="Hello Sam",
        status=EmailStatus.PENDING,
        idempotency_key="email-key-sam-1",
    )
    db_session.add(email)
    db_session.commit()

    # Start campaign
    start_resp = client.post(
        f"/api/campaigns/{camp.id}/start",
        headers=tenant_a["headers"],
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "started"
    assert start_resp.json()["jobs_enqueued"] == 1

    # Verify SendJob exists in DB
    job = db_session.query(SendJob).filter_by(campaign_id=camp.id).first()
    assert job is not None
    assert job.email_record_id == email.id


def test_pause_campaign(client: TestClient, db_session: Session, tenant_a):
    camp = Campaign(
        organization_id=tenant_a["org"].id,
        name="Running Campaign",
        status=CampaignStatus.ACTIVE,
    )
    db_session.add(camp)
    db_session.commit()

    pause_resp = client.post(
        f"/api/campaigns/{camp.id}/pause",
        headers=tenant_a["headers"],
    )
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    db_session.refresh(camp)
    assert camp.status == CampaignStatus.PAUSED


def test_upload_leads_csv(client: TestClient, tenant_a):
    csv_content = (
        "first_name,last_name,email,company_name,website\n"
        "Alex,Johnson,alex@example.com,TechCorp,https://techcorp.local\n"
        "Sarah,Connor,sarah@example.com,Cyberdyne,https://cyberdyne.local\n"
    )
    file = io.BytesIO(csv_content.encode("utf-8"))

    resp = client.post(
        "/api/leads/upload-csv",
        files={"file": ("leads.csv", file, "text/csv")},
        headers=tenant_a["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 2


def test_domain_dns_check_endpoint(client: TestClient, tenant_a):
    resp = client.get("/api/domains/check?domain=google.com", headers=tenant_a["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "google.com"
    assert "has_mx" in data
    assert "has_spf" in data
    assert "health_score" in data
