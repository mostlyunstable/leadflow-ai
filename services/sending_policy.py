"""
Sending Policy Engine.
Enforces real deliverability guardrails:
1. Hourly & daily account limits.
2. Account health and status verification.
3. Domain bounce rate thresholds (circuit breaker).
4. Recipient suppression list (unsubscribed or bounced leads).
5. Inter-send pacing intervals.
Replaces simplistic local integer counters with an evidence-based compliance gate.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import logging

from sqlalchemy.orm import Session

from core.config import settings
from database.models import (
    EmailProviderAccount, Campaign, Lead, LeadStatus, SuppressionEntry, utc_now
)

logger = logging.getLogger("leadflow.policy")


@dataclass
class PolicyDecision:
    """Result of a sending policy evaluation."""
    allowed: bool
    reason: str
    suggested_delay_seconds: int = 0
    circuit_broken: bool = False


class SendingPolicyEngine:
    """
    Evaluates campaign, sender account, and recipient state prior to dispatch.
    Acts as a strict pre-flight gatekeeper.
    """

    def __init__(
        self,
        hourly_limit: Optional[int] = None,
        daily_limit: Optional[int] = None,
        max_bounce_rate_percent: Optional[float] = None,
    ):
        self.hourly_limit = hourly_limit or settings.HOURLY_SEND_LIMIT
        self.daily_limit = daily_limit or settings.DAILY_SEND_LIMIT
        self.max_bounce_rate = max_bounce_rate_percent or settings.MAX_BOUNCE_RATE_PERCENT

    def evaluate(
        self,
        session: Session,
        account: EmailProviderAccount,
        campaign: Campaign,
        lead: Lead,
    ) -> PolicyDecision:
        """
        Evaluate all sending policy rules before an email is dispatched.
        Returns PolicyDecision.
        """
        now = utc_now()

        # Rule 1: Account Health & Status Check
        if not account.is_active:
            return PolicyDecision(
                allowed=False,
                reason=f"Sender account '{account.account_email}' is marked inactive",
            )
        if not account.is_healthy:
            return PolicyDecision(
                allowed=False,
                reason=f"Sender account '{account.account_email}' is unhealthy: {account.error_message}",
            )

        # Rule 2: Recipient Suppression Check (Do Not Contact)
        if lead.status in (LeadStatus.UNSUBSCRIBED, LeadStatus.BOUNCED):
            return PolicyDecision(
                allowed=False,
                reason=f"Recipient {lead.email} is in suppression status ({lead.status.value})",
            )
        suppressed = session.query(SuppressionEntry).filter_by(
            organization_id=campaign.organization_id,
            email=lead.email,
        ).first()
        if suppressed:
            return PolicyDecision(
                allowed=False,
                reason=f"Recipient {lead.email} is in suppression list ({suppressed.reason.value})",
            )

        # Rule 3: Campaign State & Limits
        if campaign.status.value != "active":
            return PolicyDecision(
                allowed=False,
                reason=f"Campaign {campaign.id} is not ACTIVE (status: {campaign.status.value})",
            )

        # Rule 4: Domain / Campaign Bounce Rate Circuit Breaker
        if campaign.total_sent and campaign.total_sent >= 20:
            bounce_rate = (campaign.total_bounces / campaign.total_sent) * 100
            if bounce_rate > self.max_bounce_rate:
                logger.error(
                    f"Campaign {campaign.id} exceeded max bounce rate ({bounce_rate:.1f}% > {self.max_bounce_rate}%). "
                    "Tripping circuit breaker!"
                )
                return PolicyDecision(
                    allowed=False,
                    reason=f"High bounce rate ({bounce_rate:.1f}%) exceeds safety limit ({self.max_bounce_rate}%)",
                    circuit_broken=True,
                )

        # Reset daily counters if day has changed
        today_str = now.strftime("%Y-%m-%d")
        if account.last_reset_date and account.last_reset_date != today_str:
            account.sends_today = 0
            account.sends_this_hour = 0
        account.last_reset_date = today_str

        # Rule 5: Daily Send Limit Check
        daily_cap = min(self.daily_limit, campaign.daily_limit or self.daily_limit)
        if account.sends_today >= daily_cap:
            return PolicyDecision(
                allowed=False,
                reason=f"Account '{account.account_email}' reached daily limit ({account.sends_today}/{daily_cap})",
                suggested_delay_seconds=3600,
            )

        # Rule 6: Hourly Send Limit Check
        if account.sends_this_hour >= self.hourly_limit:
            return PolicyDecision(
                allowed=False,
                reason=f"Account '{account.account_email}' reached hourly limit ({account.sends_this_hour}/{self.hourly_limit})",
                suggested_delay_seconds=600,
            )

        # Rule 7: Minimum Inter-Send Delay Pacing
        if account.last_send_at:
            # Ensure last_send_at is timezone-aware
            last_send = account.last_send_at
            if last_send.tzinfo is None:
                last_send = last_send.replace(tzinfo=timezone.utc)
            elapsed = (now - last_send).total_seconds()
            if elapsed < settings.MIN_DELAY_SECONDS:
                wait_time = int(settings.MIN_DELAY_SECONDS - elapsed) + 1
                return PolicyDecision(
                    allowed=False,
                    reason=f"Pacing delay: must wait {wait_time}s before sending next email from this account",
                    suggested_delay_seconds=wait_time,
                )

        # All policies satisfied
        return PolicyDecision(
            allowed=True,
            reason="Sending policy verified and approved",
        )

    def record_send(
        self,
        session: Session,
        account: EmailProviderAccount,
    ):
        """Update rate limiting counters and timestamps on successful dispatch."""
        now = utc_now()
        account.sends_today += 1
        account.sends_this_hour += 1
        account.last_send_at = now
        session.flush()
