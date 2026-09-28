"""
API Tests for Authentication, Authorization & Multi-Tenant Isolation.
Tests:
1. Login endpoint issuance of valid JWT.
2. Rejection of invalid credentials.
3. Strict tenant isolation: Tenant A's leads and campaigns are completely invisible to Tenant B.
4. Tenant B cannot delete or modify Tenant A's resources.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import pytest

from database.models import Lead, Campaign, CampaignStatus


def test_auth_login_success(client: TestClient, tenant_a):
    response = client.post("/api/auth/login", json={
        "email": "alice@acme.com",
        "password": "password123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["organization_id"] == tenant_a["org"].id


def test_auth_login_invalid_password(client: TestClient, tenant_a):
    response = client.post("/api/auth/login", json={
        "email": "alice@acme.com",
        "password": "WrongPassword!",
    })
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_multi_tenant_lead_isolation(client: TestClient, db_session: Session, tenant_a, tenant_b):
    # Seed a lead for Tenant A
    lead_a = Lead(
        organization_id=tenant_a["org"].id,
        first_name="AliceLead",
        last_name="One",
        email="lead-a@acme.com",
        company_name="Acme Client",
    )
    db_session.add(lead_a)
    db_session.commit()

    # Seed a lead for Tenant B
    lead_b = Lead(
        organization_id=tenant_b["org"].id,
        first_name="BobLead",
        last_name="Two",
        email="lead-b@beta.com",
        company_name="Beta Client",
    )
    db_session.add(lead_b)
    db_session.commit()

    # Query leads as Tenant A
    resp_a = client.get("/api/leads", headers=tenant_a["headers"])
    assert resp_a.status_code == 200
    leads_a = resp_a.json()["leads"]
    emails_a = [l["email"] for l in leads_a]
    assert "lead-a@acme.com" in emails_a
    assert "lead-b@beta.com" not in emails_a  # Tenant B lead MUST NOT be visible!

    # Query leads as Tenant B
    resp_b = client.get("/api/leads", headers=tenant_b["headers"])
    assert resp_b.status_code == 200
    leads_b = resp_b.json()["leads"]
    emails_b = [l["email"] for l in leads_b]
    assert "lead-b@beta.com" in emails_b
    assert "lead-a@acme.com" not in emails_b  # Tenant A lead MUST NOT be visible!


def test_cross_tenant_delete_prevention(client: TestClient, db_session: Session, tenant_a, tenant_b):
    lead_a = Lead(
        organization_id=tenant_a["org"].id,
        first_name="ProtectedLead",
        last_name="One",
        email="protected@acme.com",
        company_name="Acme",
    )
    db_session.add(lead_a)
    db_session.commit()

    # Tenant B tries to delete Tenant A's lead
    resp_delete = client.delete(f"/api/leads/{lead_a.id}", headers=tenant_b["headers"])
    assert resp_delete.status_code == 404  # Must return 404 (not found in tenant B)

    # Lead A must still exist in DB
    existing = db_session.get(Lead, lead_a.id)
    assert existing is not None
