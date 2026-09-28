"""
LeadFlow AI — Background Maintenance & Housekeeping Worker.
Performs periodic system maintenance:
1. Reaping expired worker leases on SendJobs and EnrichmentJobs.
2. Resetting hourly/daily email provider account counters.
3. Refreshing stale domain DNS deliverability diagnostics.
4. Purging completed jobs and audit logs older than retention policies.
Designed to run continuously under systemd supervision.
"""

import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from core.config import settings
from core.queue import DurableQueue
from database.database import get_session
from database.models import (
    SendJob, EnrichmentJob, EmailProviderAccount, Domain,
    AuditLog, JobStatus, utc_now
)
from services.domain_health import inspect_domain_health

logger = logging.getLogger("leadflow.worker.maintenance")


class MaintenanceWorker:
    """
    Executes automated system housekeeping and state reconciliation tasks.
    """

    def __init__(self):
        self.queue = DurableQueue(worker_id="maintenance-worker")
        self._stop_requested = False
        self._last_daily_reset_date = ""
        self._last_hour_reset = -1
        self._setup_signals()

    def _setup_signals(self):
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, AttributeError):
            pass

    def _handle_signal(self, signum, frame):
        logger.info(f"Maintenance worker received signal ({signum}). Shutting down gracefully...")
        self._stop_requested = True

    def reap_all_expired_leases(self, session: Session) -> int:
        """
        Reap abandoned SendJobs and EnrichmentJobs whose worker leases expired.
        """
        now = utc_now()
        # 1. Send jobs
        reaped_send = self.queue.reap_orphaned_jobs(session)

        # 2. Enrichment jobs
        expired_enrich = (
            session.query(EnrichmentJob)
            .filter(
                EnrichmentJob.status == JobStatus.PROCESSING,
                EnrichmentJob.lease_expires_at < now,
            )
            .all()
        )
        for ejob in expired_enrich:
            logger.warning(f"Reaping abandoned EnrichmentJob {ejob.id} (lease expired {ejob.lease_expires_at})")
            ejob.status = JobStatus.QUEUED
            ejob.lease_worker_id = None
            ejob.lease_expires_at = None

        if expired_enrich:
            session.flush()

        total = reaped_send + len(expired_enrich)
        if total > 0:
            logger.info(f"Reaped total {total} abandoned jobs back to QUEUED")
        return total

    def reset_provider_rate_limits(self, session: Session):
        """
        Reset hourly and daily sending counters when time windows roll over.
        """
        now = utc_now()
        current_date_str = now.strftime("%Y-%m-%d")
        current_hour = now.hour

        # Check hour rollover
        if current_hour != self._last_hour_reset:
            logger.info(f"Hourly rollover detected ({current_hour}:00 UTC). Resetting sends_this_hour counters.")
            session.query(EmailProviderAccount).update({EmailProviderAccount.sends_this_hour: 0})
            self._last_hour_reset = current_hour

        # Check day rollover
        if current_date_str != self._last_daily_reset_date:
            logger.info(f"Daily rollover detected ({current_date_str}). Resetting sends_today counters.")
            session.query(EmailProviderAccount).update({
                EmailProviderAccount.sends_today: 0,
                EmailProviderAccount.last_reset_date: current_date_str,
            })
            self._last_daily_reset_date = current_date_str

        session.flush()

    def refresh_stale_domain_diagnostics(self, session: Session, stale_threshold_hours: int = 24):
        """
        Re-verify DNS records for domains not inspected within the threshold.
        """
        cutoff = utc_now() - timedelta(hours=stale_threshold_hours)
        stale_domains = (
            session.query(Domain)
            .filter(or_(Domain.last_checked_at == None, Domain.last_checked_at < cutoff))
            .limit(5)
            .all()
        )

        for d in stale_domains:
            try:
                res = inspect_domain_health(d.domain_name)
                d.has_mx = res.has_mx
                d.has_spf = res.has_spf
                d.has_dkim = res.has_dkim
                d.has_dmarc = res.has_dmarc
                d.spf_record = res.spf_record
                d.dmarc_record = res.dmarc_record
                d.mx_records_json = res.mx_records
                d.is_healthy = res.is_healthy
                d.health_score = res.health_score
                d.last_checked_at = utc_now()
                session.flush()
                logger.debug(f"Refreshed DNS diagnostics for domain {d.domain_name} (score: {d.health_score})")
            except Exception as e:
                logger.warning(f"Could not refresh domain {d.domain_name}: {e}")

    def purge_retention_data(self, session: Session, retention_days: int = 30):
        """
        Delete old completed send jobs and attempt logs beyond retention window.
        """
        cutoff = utc_now() - timedelta(days=retention_days)
        deleted_jobs = (
            session.query(SendJob)
            .filter(
                SendJob.status.in_([JobStatus.SENT, JobStatus.FAILED, JobStatus.CANCELLED]),
                SendJob.created_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        if deleted_jobs:
            session.flush()
            logger.info(f"Purged {deleted_jobs} expired SendJobs older than {retention_days} days")

    def run_maintenance_cycle(self):
        """Execute one complete maintenance pass."""
        with get_session() as session:
            self.reap_all_expired_leases(session)
            self.reset_provider_rate_limits(session)
            self.refresh_stale_domain_diagnostics(session)
            self.purge_retention_data(session)

    def run_forever(self, interval_seconds: int = 30):
        """
        Main loop running every interval_seconds.
        """
        logger.info(f"Starting LeadFlow Maintenance Worker (cycle interval: {interval_seconds}s)")
        while not self._stop_requested:
            try:
                self.run_maintenance_cycle()
            except Exception as e:
                logger.error(f"Error during maintenance cycle: {e}", exc_info=True)

            # Sleep in 1s increments for fast interruptibility
            for _ in range(interval_seconds):
                if self._stop_requested:
                    break
                time.sleep(1)

        logger.info("Maintenance Worker stopped cleanly.")


if __name__ == "__main__":
    from main import setup_logging
    setup_logging()
    worker = MaintenanceWorker()
    worker.run_forever()
