"""
Integration Tests for Database Transactions, Constraints & Multi-Tenant Boundaries.
Tests:
1. Multi-tenant unique constraints (same email allowed across different orgs, rejected within same org).
2. Cascade deletes on tenant teardown.
3. Transaction rollback guarantees on unexpected error.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import (
    Organization, Lead, Campaign, CampaignStatus, EmailRecord, EmailStatus, SendJob
)


def test_scoped_email_uniqueness_per_tenant(db_session: Session):
    org_a = Organization(name="Tenant A", slug="tenant-a")
    org_b = Organization(name="Tenant B", slug="tenant-b")
    db_session.add_all([org_a, org_b])
    db_session.commit()

    # Lead with same email in Tenant A
    lead_a1 = Lead(
        organization_id=org_a.id,
        first_name="Carl",
        last_name="Sagan",
        email="carl@cosmos.local",
        company_name="Cosmos A",
    )
    db_session.add(lead_a1)
    db_session.commit()

    # Same email in Tenant B should be completely allowed! (Multi-tenant scoped)
    lead_b1 = Lead(
        organization_id=org_b.id,
        first_name="Carl",
        last_name="Sagan",
        email="carl@cosmos.local",
        company_name="Cosmos B",
    )
    db_session.add(lead_b1)
    db_session.commit()
    assert lead_b1.id is not None

    # Duplicate email WITHIN same Tenant A must raise IntegrityError
    lead_a2 = Lead(
        organization_id=org_a.id,
        first_name="Carl",
        last_name="Duplicate",
        email="carl@cosmos.local",
        company_name="Cosmos A Clone",
    )
    db_session.add(lead_a2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cascade_delete_on_organization_removal(db_session: Session):
    org = Organization(name="Disposable Org", slug="disposable")
    db_session.add(org)
    db_session.flush()

    camp = Campaign(organization_id=org.id, name="Disposable Camp", status=CampaignStatus.ACTIVE)
    db_session.add(camp)
    db_session.flush()

    lead = Lead(
        organization_id=org.id,
        first_name="Temp",
        last_name="Lead",
        email="temp@disposable.local",
        company_name="Temp",
    )
    db_session.add(lead)
    db_session.commit()

    lead_id = lead.id
    camp_id = camp.id

    # Deleting organization cascades and removes child campaigns and leads
    db_session.delete(org)
    db_session.commit()

    assert db_session.get(Lead, lead_id) is None
    assert db_session.get(Campaign, camp_id) is None


def test_transaction_rollback_preserves_consistency(db_session: Session):
    org = Organization(name="Rollback Org", slug="rollback-org")
    db_session.add(org)
    db_session.commit()

    initial_lead_count = db_session.query(Lead).filter_by(organization_id=org.id).count()

    try:
        lead_valid = Lead(
            organization_id=org.id,
            first_name="Valid",
            last_name="One",
            email="valid@test.local",
            company_name="Test",
        )
        db_session.add(lead_valid)
        db_session.flush()

        # Simulate error mid-transaction
        raise RuntimeError("Simulated transaction failure")
    except RuntimeError:
        db_session.rollback()

    # Count must remain untouched
    after_count = db_session.query(Lead).filter_by(organization_id=org.id).count()
    assert after_count == initial_lead_count
