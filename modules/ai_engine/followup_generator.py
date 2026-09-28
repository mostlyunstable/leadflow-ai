"""
Follow-Up Email Generator.
Generates contextual follow-ups referencing previous emails with new angles and value.
Uses LLMProvider with Pydantic validation and quality checks.
"""

import json
import logging
from typing import Optional, Dict, Any

from core.config import settings
from database.database import get_session
from database.models import (
    Lead, EmailRecord, EmailType, EmailStatus, LeadStatus, utc_now
)
from modules.ai_engine.ai_utils import sanitize_input, check_spam_words
from modules.ai_engine.llm_provider import get_llm_provider, GeneratedEmailOutput

logger = logging.getLogger("leadflow.followup")

FOLLOWUP_1_PROMPT = """You are writing a follow-up cold email. This is the FIRST follow-up (2 days after the initial email).

RULES:
1. Under 80 words total.
2. Reference the previous message casually without guilt-tripping.
3. Introduce ONE new angle, observation, or brief idea.
4. Soft CTA question.
5. Plain text only.

Return ONLY a JSON object:
{"subject": "Re: [original subject]", "body": "..."}"""

FOLLOWUP_2_PROMPT = """You are writing the FINAL breakup cold email (5 days after initial email).

RULES:
1. Under 60 words total.
2. Polite, respectful breakup message acknowledging they may be busy or it's not a priority.
3. No pressure, friendly tone.
4. Plain text only.

Return ONLY a JSON object:
{"subject": "Re: [original subject]", "body": "..."}"""


def generate_followup(
    lead: Lead,
    original_email: EmailRecord,
    followup_type: EmailType,
    previous_followup: Optional[EmailRecord] = None,
    provider: Optional[Any] = None,
) -> Dict[str, str]:
    """
    Generate contextual follow-up email.
    """
    llm = provider or get_llm_provider()
    system_prompt = FOLLOWUP_1_PROMPT if followup_type == EmailType.FOLLOWUP_1 else FOLLOWUP_2_PROMPT

    context = (
        f"Recipient: {sanitize_input(lead.first_name)} {sanitize_input(lead.last_name)}\n"
        f"Company: {sanitize_input(lead.company_name)}\n"
        f"Original Subject: {original_email.subject}\n"
        f"Original Body: {original_email.body[:400]}"
    )
    if previous_followup:
        context += f"\nPrevious Follow-Up: {previous_followup.body[:200]}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Write the follow-up for this lead:\n{context}"},
    ]

    output: GeneratedEmailOutput = llm.generate_email(messages)

    # Ensure subject starts with 'Re: '
    subj = output.subject
    orig_clean = original_email.subject.replace("Re: ", "").strip()
    if not subj.lower().startswith("re:"):
        subj = f"Re: {orig_clean}"

    body = output.body.rstrip() + settings.UNSUBSCRIBE_FOOTER

    return {
        "subject": subj,
        "body": body,
    }


def generate_followup_for_lead(
    lead_id: int,
    followup_type: EmailType,
) -> Optional[Dict[str, Any]]:
    """Generate and store follow-up email record."""
    with get_session() as session:
        lead = session.get(Lead, lead_id)
        if not lead:
            return None

        # Verify not replied/bounced/unsubscribed
        if lead.status in (LeadStatus.REPLIED, LeadStatus.BOUNCED, LeadStatus.UNSUBSCRIBED):
            return None

        original = (
            session.query(EmailRecord)
            .filter_by(lead_id=lead.id, email_type=EmailType.INITIAL, status=EmailStatus.SENT)
            .first()
        )
        if not original:
            return None

        prev_followup = None
        if followup_type == EmailType.FOLLOWUP_2:
            prev_followup = (
                session.query(EmailRecord)
                .filter_by(lead_id=lead.id, email_type=EmailType.FOLLOWUP_1, status=EmailStatus.SENT)
                .first()
            )

        try:
            data = generate_followup(lead, original, followup_type, prev_followup)
            import uuid
            idempotency_key = f"followup:{lead.organization_id}:{lead.id}:{followup_type.value}:{uuid.uuid4().hex[:8]}"

            record = EmailRecord(
                organization_id=lead.organization_id,
                campaign_id=lead.campaign_id,
                lead_id=lead.id,
                subject=data["subject"],
                body=data["body"],
                email_type=followup_type,
                status=EmailStatus.PENDING,
                idempotency_key=idempotency_key,
                provider_thread_id=original.provider_thread_id,
            )
            session.add(record)
            session.flush()

            return {
                "lead_id": lead.id,
                "email": lead.email,
                "subject": record.subject,
                "body": record.body,
                "record_id": record.id,
            }
        except Exception as e:
            logger.error(f"Failed to generate follow-up for lead {lead_id}: {e}")
            return None
