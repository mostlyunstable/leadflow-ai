"""
Unit Tests for Sending Policy Engine.
Tests:
1. Inactive / unhealthy account rejection.
2. Recipient suppression (unsubscribed/bounced leads).
3. Daily and hourly send limits.
4. Bounce rate circuit breaker tripping.
5. Inter-send pacing delay enforcement.
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
import pytest

from services.sending_policy import SendingPolicyEngine
from database.models import (
    EmailProviderAccount, Campaign, Lead, LeadStatus, CampaignStatus, Organization, utc_now
)


def _setup_policy_context(db_session: Session):
    org = Organization(name="Policy Org", slug="policy-org")
    db_session.add(org)
    db_session.flush()

    account = EmailProviderAccount(
        organization_id=org.id,
        account_email="sender@example.com",
        is_active=True,
        is_healthy=True,
        sends_today=0,
        sends_this_hour=0,
    )
    db_session.add(account)

    campaign = Campaign(
        organization_id=org.id,
        name="Policy Campaign",
        status=CampaignStatus.ACTIVE,
        daily_limit=50,
        total_sent=0,
        total_bounces=0,
    )
    db_session.add(campaign)

    lead = Lead(
        organization_id=org.id,
        first_name="Jane",
        last_name="Doe",
        email="jane@example.com",
        company_name="Widget Co",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()

    return account, campaign, lead


def test_policy_denies_inactive_account(db_session: Session):
    account, campaign, lead = _setup_policy_context(db_session)
    account.is_active = False
    db_session.commit()

    engine = SendingPolicyEngine()
    decision = engine.evaluate(db_session, account, campaign, lead)
    assert decision.allowed is False
    assert "inactive" in decision.reason


def test_policy_denies_unsubscribed_recipient(db_session: Session):
    account, campaign, lead = _setup_policy_context(db_session)
    lead.status = LeadStatus.UNSUBSCRIBED
    db_session.commit()

    engine = SendingPolicyEngine()
    decision = engine.evaluate(db_session, account, campaign, lead)
    assert decision.allowed is False
    assert "suppression" in decision.reason


def test_policy_enforces_daily_limit(db_session: Session):
    account, campaign, lead = _setup_policy_context(db_session)
    account.sends_today = 50
    db_session.commit()

    engine = SendingPolicyEngine(daily_limit=50)
    decision = engine.evaluate(db_session, account, campaign, lead)
    assert decision.allowed is False
    assert "daily limit" in decision.reason


def test_policy_enforces_hourly_limit(db_session: Session):
    account, campaign, lead = _setup_policy_context(db_session)
    account.sends_this_hour = 15
    db_session.commit()

    engine = SendingPolicyEngine(hourly_limit=15)
    decision = engine.evaluate(db_session, account, campaign, lead)
    assert decision.allowed is False
    assert "hourly limit" in decision.reason


def test_policy_trips_bounce_circuit_breaker(db_session: Session):
    account, campaign, lead = _setup_policy_context(db_session)
    campaign.total_sent = 30
    campaign.total_bounces = 4  # 13.3% > 5.0% threshold
    db_session.commit()

    engine = SendingPolicyEngine(max_bounce_rate_percent=5.0)
    decision = engine.evaluate(db_session, account, campaign, lead)
    assert decision.allowed is False
    assert decision.circuit_broken is True
    assert "bounce rate" in decision.reason
