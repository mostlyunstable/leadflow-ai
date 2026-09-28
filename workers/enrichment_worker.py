"""
LeadFlow AI — Dedicated Asynchronous Enrichment Worker.
Drains enrichment_jobs using atomic database lease locks, performs
SSRF-safe website analysis and AI feature extraction, and records results.
Survives process restarts and cleans up gracefully on SIGTERM/SIGINT.
"""

import logging
import signal
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from typing import Optional

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from core.config import settings
from database.database import get_session
from database.models import (
    EnrichmentJob, JobStatus, Lead, LeadStatus, utc_now
)
from modules.lead_enrichment.enricher import LeadEnricher

logger = logging.getLogger("leadflow.worker.enrichment")


class EnrichmentWorker:
    """
    Background worker that continuously pulls and processes EnrichmentJobs.
    """

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"enrich-worker-{uuid.uuid4().hex[:8]}"
        self.enricher = LeadEnricher()
        self._stop_requested = False
        self._setup_signals()

    def _setup_signals(self):
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, AttributeError):
            pass

    def _handle_signal(self, signum, frame):
        logger.info(f"Enrichment worker {self.worker_id} received signal ({signum}). Finishing active job...")
        self._stop_requested = True

    def claim_enrichment_job(self, session: Session, lease_seconds: int = 120) -> Optional[EnrichmentJob]:
        """
        Atomically claim a queued or expired-lease enrichment job.
        """
        now = utc_now()
        lease_expiration = now + timedelta(seconds=lease_seconds)

        query = (
            session.query(EnrichmentJob)
            .filter(
                or_(
                    and_(
                        EnrichmentJob.status == JobStatus.QUEUED,
                    ),
                    and_(
                        EnrichmentJob.status == JobStatus.PROCESSING,
                        EnrichmentJob.lease_expires_at < now,
                    ),
                )
            )
            .order_by(EnrichmentJob.created_at.asc())
        )

        job = query.with_for_update(skip_locked=True).first() if "sqlite" not in settings.DATABASE_URL.lower() else query.first()

        if not job:
            return None

        job.status = JobStatus.PROCESSING
        job.lease_worker_id = self.worker_id
        job.lease_expires_at = lease_expiration
        job.attempt_count += 1
        session.flush()

        logger.debug(f"EnrichmentWorker {self.worker_id} claimed job {job.id} for lead {job.lead_id}")
        return job

    def process_next_job(self, session: Optional[Session] = None) -> bool:
        """
        Process a single enrichment job. Returns True if job was processed, False if queue empty.
        """
        if session is not None:
            return self._execute(session)

        with get_session() as sess:
            return self._execute(sess)

    def _execute(self, session: Session) -> bool:
        job = self.claim_enrichment_job(session)
        if not job:
            return False

        job_id = job.id
        lead_id = job.lead_id

        try:
            success = self.enricher.enrich_lead(lead_id)
            # Re-fetch job in active session
            active_job = session.get(EnrichmentJob, job_id)
            if active_job:
                active_job.status = JobStatus.SENT if success else JobStatus.FAILED
                active_job.lease_worker_id = None
                active_job.lease_expires_at = None
                session.flush()
            logger.info(f"EnrichmentJob {job_id} for lead {lead_id} completed (success={success})")
        except Exception as e:
            logger.error(f"EnrichmentJob {job_id} encountered unhandled exception: {e}")
            active_job = session.get(EnrichmentJob, job_id)
            if active_job:
                active_job.status = JobStatus.FAILED
                active_job.error_message = str(e)
                active_job.lease_worker_id = None
                active_job.lease_expires_at = None
                session.flush()

        return True

    def run_forever(self, poll_interval: float = 2.0):
        """
        Main execution loop for systemd supervision.
        """
        logger.info(f"Starting LeadFlow Enrichment Worker [{self.worker_id}]")
        while not self._stop_requested:
            try:
                processed = self.process_next_job()
                if not processed:
                    time.sleep(poll_interval)
            except Exception as e:
                logger.error(f"Error in enrichment worker loop: {e}", exc_info=True)
                time.sleep(poll_interval * 2)

        logger.info(f"Enrichment Worker [{self.worker_id}] stopped cleanly.")


if __name__ == "__main__":
    from main import setup_logging
    setup_logging()
    worker = EnrichmentWorker()
    worker.run_forever()
