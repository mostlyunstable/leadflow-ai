"""
Multi-Account Manager — Manages multiple Gmail accounts for scaling outreach.
Handles round-robin selection, daily count tracking, and health monitoring.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from database.database import get_session
from database.models import GmailAccount
from modules.email_sender.gmail_client import GmailClient

logger = logging.getLogger(__name__)


class AccountManager:
    """
    Manages a pool of Gmail accounts for sending.
    Implements round-robin selection with daily limits and health checks.
    """

    def __init__(self):
        self._clients: dict[str, GmailClient] = {}
        self._round_robin_index = 0

    def add_account(self, email: str, display_name: str = None) -> dict:
        """
        Register a new Gmail account for sending.
        Will trigger OAuth flow if no token exists.
        
        Args:
            email: Gmail address
            display_name: Friendly name for the account
            
        Returns:
            dict with account details
        """
        with get_session() as session:
            existing = session.query(GmailAccount).filter_by(email=email).first()
            if existing:
                return {
                    "status": "exists",
                    "email": email,
                    "message": "Account already registered",
                }

            # Try to authenticate
            client = GmailClient(email)
            try:
                client.authenticate()
                healthy = True
                error = None
            except Exception as e:
                healthy = False
                error = str(e)
                logger.error(f"Authentication failed for {email}: {e}")

            account = GmailAccount(
                email=email,
                display_name=display_name or email.split("@")[0],
                token_file=client.token_path,
                is_active=True,
                is_healthy=healthy,
                error_message=error,
                last_reset_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
            session.add(account)

            if healthy:
                self._clients[email] = client

            return {
                "status": "added" if healthy else "auth_failed",
                "email": email,
                "healthy": healthy,
                "error": error,
            }

    def get_available_account(self, campaign_id: int = None) -> Optional[GmailClient]:
        """
        Get the next available Gmail account using round-robin.
        Skips accounts that have reached daily limits or are unhealthy.

        Args:
            campaign_id: If provided, uses the campaign's warmup-aware daily limit.

        Returns:
            GmailClient instance or None if no accounts available
        """
        with get_session() as session:
            accounts = (
                session.query(GmailAccount)
                .filter_by(is_active=True, is_healthy=True)
                .all()
            )

            if not accounts:
                logger.error("No active/healthy Gmail accounts available")
                return None

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Resolve per-account daily limit (warmup-aware if campaign provided)
            from config.settings import DAILY_SEND_LIMIT
            daily_limit = DAILY_SEND_LIMIT
            if campaign_id:
                from database.models import Campaign
                campaign = session.get(Campaign, campaign_id)
                if campaign and campaign.current_daily_limit:
                    # Spread campaign limit evenly across active accounts
                    daily_limit = max(1, campaign.current_daily_limit // len(accounts))

            # Try each account starting from round-robin index
            for i in range(len(accounts)):
                idx = (self._round_robin_index + i) % len(accounts)
                account = accounts[idx]

                # Reset daily count if new day
                if account.last_reset_date != today:
                    account.sends_today = 0
                    account.last_reset_date = today

                # Check daily limit (per account, warmup-aware)
                if account.sends_today >= daily_limit:
                    continue

                # Get or create client
                if account.email not in self._clients:
                    client = GmailClient(account.email)
                    try:
                        client.authenticate()
                        self._clients[account.email] = client
                    except Exception as e:
                        account.is_healthy = False
                        account.error_message = str(e)
                        logger.error(f"Failed to auth {account.email}: {e}")
                        continue

                self._round_robin_index = (idx + 1) % len(accounts)
                return self._clients[account.email]

            logger.warning("All Gmail accounts have reached their daily limits")
            return None

    def record_send(self, email: str):
        """Record a successful send for an account."""
        with get_session() as session:
            account = session.query(GmailAccount).filter_by(email=email).first()
            if account:
                account.sends_today += 1
                account.last_send_at = datetime.now(timezone.utc)

    def list_accounts(self) -> list[dict]:
        """List all registered accounts with their status."""
        with get_session() as session:
            accounts = session.query(GmailAccount).all()
            return [
                {
                    "id": a.id,
                    "email": a.email,
                    "display_name": a.display_name,
                    "is_active": a.is_active,
                    "is_healthy": a.is_healthy,
                    "sends_today": a.sends_today,
                    "last_send_at": a.last_send_at.isoformat() if a.last_send_at else None,
                    "error": a.error_message,
                }
                for a in accounts
            ]

    def health_check_all(self) -> dict:
        """Run health check on all active accounts."""
        results = {"healthy": 0, "unhealthy": 0, "details": []}

        with get_session() as session:
            accounts = session.query(GmailAccount).filter_by(is_active=True).all()

            for account in accounts:
                if account.email in self._clients:
                    client = self._clients[account.email]
                else:
                    client = GmailClient(account.email)
                    try:
                        client.authenticate()
                        self._clients[account.email] = client
                    except Exception as e:
                        account.is_healthy = False
                        account.error_message = str(e)
                        results["unhealthy"] += 1
                        results["details"].append({"email": account.email, "healthy": False, "error": str(e)})
                        continue

                healthy = client.check_health()
                account.is_healthy = healthy

                if healthy:
                    results["healthy"] += 1
                    account.error_message = None
                else:
                    results["unhealthy"] += 1
                    account.error_message = "Health check failed"

                results["details"].append({
                    "email": account.email,
                    "healthy": healthy,
                })

        return results

    def deactivate_account(self, email: str) -> bool:
        """Deactivate a Gmail account."""
        with get_session() as session:
            account = session.query(GmailAccount).filter_by(email=email).first()
            if account:
                account.is_active = False
                if email in self._clients:
                    del self._clients[email]
                logger.info(f"Deactivated account: {email}")
                return True
            return False

    def activate_account(self, email: str) -> bool:
        """Re-activate a Gmail account."""
        with get_session() as session:
            account = session.query(GmailAccount).filter_by(email=email).first()
            if account:
                account.is_active = True
                logger.info(f"Activated account: {email}")
                return True
            return False
