"""
Personalized Cold Email Generator.
Uses LLMProvider abstraction with Pydantic validation, prompt-injection sanitization,
and content quality risk heuristics.
"""

import json
import logging
from typing import Optional, List, Dict, Any

from core.config import settings
from database.database import get_session
from database.models import (
    Lead, EmailRecord, EmailType, EmailStatus, LeadStatus, Campaign, utc_now
)
from modules.ai_engine.ai_utils import sanitize_input, check_spam_words
from modules.ai_engine.llm_provider import get_llm_provider, GeneratedEmailOutput

logger = logging.getLogger("leadflow.generator")

SYSTEM_PROMPT = """You are an expert cold email copywriter who writes emails that feel genuinely human.

RULES:
1. Write 100-150 words total (body only).
2. Tone: conversational, respectful, peer-to-peer, not salesy.
3. Subject line: 3-6 words, lowercase acceptable, no clickbait or exclamation marks.
4. First line: specific observation about their company/industry.
5. Soft call-to-action (open question, not pushy meeting link).
6. Plain text only.

Return ONLY a JSON object:
{"subject": "...", "body": "..."}"""


def generate_email(
    lead: Lead,
    high_performing_examples: Optional[List[Dict[str, Any]]] = None,
    provider: Optional[Any] = None,
) -> Dict[str, str]:
    """
    Generate a personalized initial cold email for a lead with strict schema validation.
    """
    llm = provider or get_llm_provider()

    # Sanitize user-provided fields against prompt injection
    first_name = sanitize_input(lead.first_name or "")
    last_name = sanitize_input(lead.last_name or "")
    company_name = sanitize_input(lead.company_name or "")

    context_lines = [
        f"Recipient: {first_name} {last_name}",
        f"Company: {company_name}",
    ]
    if lead.industry:
        context_lines.append(f"Industry: {sanitize_input(lead.industry)}")
    if lead.company_description:
        context_lines.append(f"Company description: {sanitize_input(lead.company_description)}")
    if lead.key_offering:
        context_lines.append(f"Key offering: {sanitize_input(lead.key_offering)}")
    if lead.website:
        context_lines.append(f"Website: {lead.website}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Write an outreach email for this prospect:\n" + "\n".join(context_lines)},
    ]

    output: GeneratedEmailOutput = llm.generate_email(messages)

    # Content quality check (risk words)
    combined = f"{output.subject} {output.body}"
    risk_words = check_spam_words(combined)
    if risk_words:
        logger.warning(f"Quality heuristic detected risk words for {lead.email}: {risk_words}. Requesting revision...")
        messages.append({"role": "assistant", "content": json.dumps(output.model_dump())})
        messages.append({
            "role": "user",
            "content": f"Please revise to remove these specific words: {', '.join(risk_words)}. Return JSON only.",
        })
        try:
            output = llm.generate_email(messages)
        except Exception as e:
            logger.warning(f"Revision request failed, keeping initial valid output: {e}")

    body = output.body.rstrip() + settings.UNSUBSCRIBE_FOOTER

    return {
        "subject": output.subject,
        "body": body,
    }


def generate_email_for_lead(lead_id: int, campaign_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Generate and persist email record for a single lead.
    """
    with get_session() as session:
        lead = session.get(Lead, lead_id)
        if not lead:
            logger.error(f"Lead {lead_id} not found")
            return None

        if lead.status in (LeadStatus.EMAILED, LeadStatus.REPLIED, LeadStatus.BOUNCED):
            logger.info(f"Lead {lead_id} already reached out to, skipping")
            return None

        try:
            email_data = generate_email(lead)

            # Generate deterministic idempotency key for this email record
            import uuid
            idempotency_key = f"email:{lead.organization_id}:{campaign_id or 0}:{lead.id}:{uuid.uuid4().hex[:8]}"

            record = EmailRecord(
                organization_id=lead.organization_id,
                campaign_id=campaign_id or lead.campaign_id,
                lead_id=lead.id,
                subject=email_data["subject"],
                body=email_data["body"],
                email_type=EmailType.INITIAL,
                status=EmailStatus.PENDING,
                idempotency_key=idempotency_key,
            )
            session.add(record)
            lead.status = LeadStatus.EMAIL_GENERATED
            session.flush()

            return {
                "lead_id": lead.id,
                "email": lead.email,
                "subject": record.subject,
                "body": record.body,
                "record_id": record.id,
            }
        except Exception as e:
            logger.error(f"Failed to generate email for lead {lead_id}: {e}")
            return None


def generate_emails_batch(
    lead_ids: Optional[List[int]] = None,
    campaign_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Generate emails in batch for eligible leads.
    """
    with get_session() as session:
        query = session.query(Lead.id).filter(
            Lead.status.in_([LeadStatus.NEW, LeadStatus.ENRICHED])
        )
        if organization_id:
            query = query.filter(Lead.organization_id == organization_id)
        if campaign_id:
            query = query.filter(Lead.campaign_id == campaign_id)
        if lead_ids:
            query = query.filter(Lead.id.in_(lead_ids))

        target_ids = [r[0] for r in query.limit(limit).all()]

    generated = 0
    failed = 0

    for lead_id in target_ids:
        res = generate_email_for_lead(lead_id, campaign_id)
        if res:
            generated += 1
        else:
            failed += 1

    return {
        "total": len(target_ids),
        "generated": generated,
        "failed": failed,
    }
