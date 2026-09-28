"""
Exhaustive Tenant Escape & BOLA/IDOR Security Attack Test Suite.
Verifies that Tenant B (Organization B) cannot access, read, mutate, start, pause,
or delete any resource belonging to Tenant A (Organization A).
"""

import pytest
from fastapi.testclient import TestClient

from database.models import (
    Campaign, CampaignStatus, Lead, LeadStatus, EmailRecord, EmailStatus,
    Reply, EmailProviderAccount, ReplyClassification
)


def test_cross_tenant_lead_read_blocked(client: TestClient, tenant_a, tenant_b, db_session):
    """Attack: Tenant B attempts to read Tenant A's lead by direct ID."""
    org_a = tenant_a["org"]
    lead_a = Lead(
        organization_id=org_a.id,
        first_name="Confidential",
        last_name="Prospect",
        email="confidential@targeta.com",
        company_name="Target A Corp",
        status=LeadStatus.NEW,
    )
    db_session.add(lead_a)
    db_session.commit()

    # Tenant B tries to read Lead A
    resp = client.get(f"/api/leads/{lead_a.id}", headers=tenant_b["headers"])
    assert resp.status_code == 404, "Tenant B must NOT be able to view Tenant A's lead!"


def test_cross_tenant_lead_delete_blocked(client: TestClient, tenant_a, tenant_b, db_session):
    """Attack: Tenant B attempts to delete Tenant A's lead by ID."""
    org_a = tenant_a["org"]
    lead_a = Lead(
        organization_id=org_a.id,
        first_name="Secure",
        last_name="Lead",
        email="secure@targeta.com",
        company_name="Target A Corp",
        status=LeadStatus.NEW,
    )
    db_session.add(lead_a)
    db_session.commit()

    # Tenant B attempts DELETE
    resp = client.delete(f"/api/leads/{lead_a.id}", headers=tenant_b["headers"])
    assert resp.status_code == 404, "Tenant B must NOT delete Tenant A's lead!"

    # Verify lead still exists in DB
    db_session.refresh(lead_a)
    assert lead_a is not None


def test_cross_tenant_campaign_manipulation_blocked(client: TestClient, tenant_a, tenant_b, db_session):
    """Attack: Tenant B attempts to start and pause Tenant A's campaign."""
    org_a = tenant_a["org"]
    campaign_a = Campaign(
        organization_id=org_a.id,
        name="Top Secret Outreach",
        status=CampaignStatus.DRAFT,
    )
    db_session.add(campaign_a)
    db_session.commit()

    # Tenant B attempts to start Tenant A's campaign
    resp_start = client.post(f"/api/campaigns/{campaign_a.id}/start", headers=tenant_b["headers"])
    assert resp_start.status_code == 404

    # Tenant B attempts to pause Tenant A's campaign
    resp_pause = client.post(f"/api/campaigns/{campaign_a.id}/pause", headers=tenant_b["headers"])
    assert resp_pause.status_code == 404


def test_cross_tenant_list_scoping(client: TestClient, tenant_a, tenant_b, db_session):
    """Attack: Tenant B attempts to list campaigns, leads, emails, replies, and accounts."""
    org_a = tenant_a["org"]
    org_b = tenant_b["org"]

    # Create resources for Tenant A
    camp_a = Campaign(organization_id=org_a.id, name="Campaign A", status=CampaignStatus.ACTIVE)
    lead_a = Lead(organization_id=org_a.id, first_name="A", last_name="A", email="a@a.com", company_name="A")
    db_session.add_all([camp_a, lead_a])
    db_session.flush()

    email_a = EmailRecord(
        organization_id=org_a.id,
        lead_id=lead_a.id,
        subject="Secret Subject A",
        body="Secret Body A",
        idempotency_key="idemp:a:1",
    )
    reply_a = Reply(
        organization_id=org_a.id,
        lead_id=lead_a.id,
        reply_body="Secret Reply A",
        classification=ReplyClassification.INTERESTED,
    )
    account_a = EmailProviderAccount(
        organization_id=org_a.id,
        account_email="sender-a@acme.com",
    )
    db_session.add_all([email_a, reply_a, account_a])

    # Create resources for Tenant B
    camp_b = Campaign(organization_id=org_b.id, name="Campaign B", status=CampaignStatus.ACTIVE)
    lead_b = Lead(organization_id=org_b.id, first_name="B", last_name="B", email="b@b.com", company_name="B")
    db_session.add_all([camp_b, lead_b])
    db_session.commit()

    # 1. Tenant B lists campaigns
    resp_c = client.get("/api/campaigns", headers=tenant_b["headers"])
    assert resp_c.status_code == 200
    campaign_names = [c["name"] for c in resp_c.json()["campaigns"]]
    assert "Campaign A" not in campaign_names
    assert "Campaign B" in campaign_names

    # 2. Tenant B lists leads
    resp_l = client.get("/api/leads", headers=tenant_b["headers"])
    assert resp_l.status_code == 200
    lead_emails = [l["email"] for l in resp_l.json()["leads"]]
    assert "a@a.com" not in lead_emails
    assert "b@b.com" in lead_emails

    # 3. Tenant B lists emails
    resp_e = client.get("/api/emails", headers=tenant_b["headers"])
    assert resp_e.status_code == 200
    email_subjects = [e["subject"] for e in resp_e.json()["emails"]]
    assert "Secret Subject A" not in email_subjects

    # 4. Tenant B lists replies
    resp_r = client.get("/api/replies", headers=tenant_b["headers"])
    assert resp_r.status_code == 200
    assert len(resp_r.json()["replies"]) == 0

    # 5. Tenant B lists sender accounts
    resp_acc = client.get("/api/accounts", headers=tenant_b["headers"])
    assert resp_acc.status_code == 200
    account_emails = [a["email"] for a in resp_acc.json()["accounts"]]
    assert "sender-a@acme.com" not in account_emails


def test_cross_tenant_analytics_isolation(client: TestClient, tenant_a, tenant_b, db_session):
    """Attack: Tenant B calls analytics/overview; verify Tenant A's metrics are never leaked."""
    org_a = tenant_a["org"]
    org_b = tenant_b["org"]

    lead_a1 = Lead(organization_id=org_a.id, first_name="L1", last_name="A", email="l1@a.com", company_name="A")
    lead_a2 = Lead(organization_id=org_a.id, first_name="L2", last_name="A", email="l2@a.com", company_name="A")
    lead_b1 = Lead(organization_id=org_b.id, first_name="L1", last_name="B", email="l1@b.com", company_name="B")
    db_session.add_all([lead_a1, lead_a2, lead_b1])
    db_session.commit()

    resp_b = client.get("/api/analytics/overview", headers=tenant_b["headers"])
    assert resp_b.status_code == 200
    data = resp_b.json()
    assert data["overview"]["total_leads"] == 1, "Tenant B must only count its own 1 lead, not Tenant A's 2 leads!"
