"""
Lead Enrichment Engine.
Uses the layered SSRF-safe enrichment pipeline to extract verified company context.
Updates lead profiles and creates persistent EnrichmentResult audit records.
"""

import logging
from typing import Optional, Dict, Any

from core.config import settings
from database.database import get_session
from database.models import Lead, LeadStatus, Company, EnrichmentResult, utc_now
from modules.lead_enrichment.pipeline import EnrichmentPipeline, ExtractedProfile

logger = logging.getLogger("leadflow.enricher")


class LeadEnricher:
    """
    Enriches leads with website data using SSRF-safe layered fetching.
    """

    def __init__(self):
        self.pipeline = EnrichmentPipeline()

    def enrich_lead(self, lead_id: int) -> bool:
        """
        Enrich a single lead by scraping and analyzing their company website.
        Stores persistent audit records in `enrichment_results`.
        """
        with get_session() as session:
            lead = session.get(Lead, lead_id)
            if not lead:
                logger.error(f"Lead {lead_id} not found for enrichment")
                return False

            if not lead.website:
                logger.info(f"Lead {lead_id} has no website URL to enrich")
                lead.status = LeadStatus.ENRICHED
                return True

            lead.status = LeadStatus.ENRICHING
            session.flush()

            # Execute pipeline
            profile: ExtractedProfile = self.pipeline.process(
                url=lead.website,
                company_name=lead.company_name or "",
            )

            # Persist enrichment audit record
            audit_record = EnrichmentResult(
                organization_id=lead.organization_id,
                lead_id=lead.id,
                target_url=lead.website,
                resolved_ip=profile.resolved_ip,
                fetch_method=profile.fetch_method,
                http_status=profile.http_status,
                title=profile.title,
                meta_description=profile.meta_description,
                headings_json=profile.headings,
                extracted_text=profile.clean_text[:1500] if profile.clean_text else None,
                summary_description=profile.company_description,
                key_offering=profile.key_offering,
                confidence_score=profile.confidence_score,
            )
            session.add(audit_record)

            if profile.confidence_score > 0.0 or not profile.error:
                lead.company_description = profile.company_description
                lead.key_offering = profile.key_offering
                lead.enriched = True
                lead.status = LeadStatus.ENRICHED
                logger.info(f"Successfully enriched lead {lead_id} ({lead.email}) with confidence {profile.confidence_score}")
                return True
            else:
                logger.warning(f"Enrichment yielded low confidence/error for lead {lead_id}: {profile.error}")
                lead.status = LeadStatus.ENRICHED  # Mark enriched with available data so funnel proceeds
                return False

    def enrich_all_pending(self, organization_id: Optional[int] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Enrich pending leads for an organization.
        """
        with get_session() as session:
            query = session.query(Lead.id).filter(
                Lead.status.in_([LeadStatus.NEW]),
                Lead.website.isnot(None),
            )
            if organization_id:
                query = query.filter(Lead.organization_id == organization_id)
            target_ids = [r[0] for r in query.limit(limit).all()]

        enriched_count = 0
        failed_count = 0

        for lead_id in target_ids:
            success = self.enrich_lead(lead_id)
            if success:
                enriched_count += 1
            else:
                failed_count += 1

        return {
            "total": len(target_ids),
            "enriched": enriched_count,
            "failed": failed_count,
        }
