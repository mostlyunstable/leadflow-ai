"""
Authentication and Server-Side RBAC Authorization Attack Test Suite.
Verifies:
1. Expired, tampered, wrong-key, malformed, and missing JWTs strictly fail with HTTP 401.
2. Server-side RBAC enforcement:
   - VIEWER is forbidden from creating campaigns, deleting leads, starting campaigns, adding accounts (HTTP 403).
   - VIEWER is permitted to view/read campaigns, leads, stats (HTTP 200).
   - ADMIN and OWNER are permitted full operational actions.
"""

import pytest
from datetime import timedelta
from fastapi.testclient import TestClient

from core.security import create_access_token
from database.models import Campaign, CampaignStatus, Lead, LeadStatus


def test_auth_attacks_fail_with_401(client: TestClient):
    """Attack: Test all malformed, expired, tampered, and missing tokens."""
    # 1. Missing header
    res_missing = client.get("/api/campaigns")
    assert res_missing.status_code == 401
    assert "Authentication required" in res_missing.json()["detail"]

    # 2. Expired JWT
    expired_token = create_access_token(
        user_id=1,
        organization_id=1,
        role="admin",
        expires_delta=timedelta(seconds=-10),  # expired in the past
    )
    res_expired = client.get("/api/campaigns", headers={"Authorization": f"Bearer {expired_token}"})
    assert res_expired.status_code == 401
    assert "expired" in res_expired.json()["detail"].lower()

    # 3. Tampered payload
    parts = expired_token.split(".")
    # Swap payload character
    tampered_token = f"{parts[0]}.eyJhZG1pbiI6IHRydWV9.{parts[2]}"
    res_tampered = client.get("/api/campaigns", headers={"Authorization": f"Bearer {tampered_token}"})
    assert res_tampered.status_code == 401
    assert "signature" in res_tampered.json()["detail"].lower()

    # 4. Malformed token (not 3 parts)
    res_malformed = client.get("/api/campaigns", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert res_malformed.status_code == 401

    # 5. Invalid API Key
    res_bad_key = client.get("/api/campaigns", headers={"X-API-Key": "completely-fake-key-123"})
    assert res_bad_key.status_code == 403


def test_rbac_viewer_prohibited_from_mutations(client: TestClient, tenant_a, db_session):
    """
    Attack: Authenticated user with role 'viewer' attempts privileged mutations.
    Server MUST reject with HTTP 403 Forbidden.
    """
    org = tenant_a["org"]

    # Generate token with role='viewer'
    viewer_token = create_access_token(user_id=999, organization_id=org.id, role="viewer")
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    # 1. VIEWER can READ campaigns and leads
    res_read_c = client.get("/api/campaigns", headers=viewer_headers)
    assert res_read_c.status_code == 200

    res_read_l = client.get("/api/leads", headers=viewer_headers)
    assert res_read_l.status_code == 200

    # 2. VIEWER cannot CREATE a campaign
    res_create_c = client.post(
        "/api/campaigns/create",
        json={"name": "Viewer Illegal Campaign", "daily_limit": 20},
        headers=viewer_headers,
    )
    assert res_create_c.status_code == 403
    assert "Operation requires one of roles" in res_create_c.json()["detail"]

    # 3. VIEWER cannot DELETE a lead
    lead = Lead(
        organization_id=org.id,
        first_name="Target",
        last_name="Lead",
        email="target@test.com",
        company_name="Test",
    )
    db_session.add(lead)
    db_session.commit()

    res_del_lead = client.delete(f"/api/leads/{lead.id}", headers=viewer_headers)
    assert res_del_lead.status_code == 403

    # 4. VIEWER cannot START a campaign
    camp = Campaign(organization_id=org.id, name="Test", status=CampaignStatus.DRAFT)
    db_session.add(camp)
    db_session.commit()

    res_start_c = client.post(f"/api/campaigns/{camp.id}/start", headers=viewer_headers)
    assert res_start_c.status_code == 403

    # 5. VIEWER cannot ADD an email sender account
    res_add_acc = client.post(
        "/api/accounts/add",
        data={"email": "viewer_sender@test.com"},
        headers=viewer_headers,
    )
    assert res_add_acc.status_code == 403


def test_rbac_admin_and_owner_permitted(client: TestClient, tenant_a):
    """Verify ADMIN and OWNER roles have full authorization for mutations."""
    # Tenant A fixture is OWNER
    res_create = client.post(
        "/api/campaigns/create",
        json={"name": "Owner Valid Campaign", "daily_limit": 50},
        headers=tenant_a["headers"],
    )
    assert res_create.status_code == 200
    assert res_create.json()["status"] == "created"
