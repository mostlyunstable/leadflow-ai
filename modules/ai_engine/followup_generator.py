"""
Follow-Up Email Generator — Creates contextual follow-up emails.
Each follow-up references the previous email and adds new value.
"""

import json
import logging
from typing import Optional

from config.settings import (
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    UNSUBSCRIBE_FOOTER,
)
from database.database import get_session
from database.models import Lead, EmailRecord, EmailType, EmailStatus, LeadStatus
from modules.ai_engine.ai_utils import (
    get_openai_client,
    clean_json_response,
    check_spam_words,
    sanitize_input,
)

logger = logging.getLogger(__name__)


FOLLOWUP_1_PROMPT = """You are writing a follow-up cold email. This is the FIRST follow-up (sent 2 days after the original).

RULES:
1. Maximum 80 words
2. Reference the previous email naturally (e.g., "Following up on my note about...")
3. Add ONE new angle or piece of value — don't repeat the original
4. Tone: casual, brief, human
5. Soft CTA — question format
6. No spam trigger words
7. Use "Re: [original subject]" format: keep the same subject but add "Re: " prefix
8. No exclamation marks, no emoji
9. Plain text only

Return ONLY valid JSON:
{"subject": "Re: [original subject]", "body": "..."}"""


FOLLOWUP_2_PROMPT = """You are writing the FINAL follow-up cold email. This is the SECOND follow-up (sent 5 days after the original).

RULES:
1. Maximum 60 words — extremely concise
2. This is the LAST attempt — make it count
3. Frame it as a "breakup" or final check-in
4. Don't be needy or desperate
5. One simple question or statement
6. Tone: friendly, understanding, no pressure
7. Use "Re: [original subject]" format
8. No spam trigger words, no exclamation marks, no emoji
9. Plain text only

Return ONLY valid JSON:
{"subject": "Re: [original subject]", "body": "..."}"""


def generate_followup(
    lead: Lead,
    original_email: EmailRecord,
    followup_type: EmailType,
    previous_followup: Optional[EmailRecord] = None,
) -> dict:
    """
    Generate a follow-up email based on the original email and lead data.
    
    Args:
        lead: The lead to follow up with
        original_email: The initial email that was sent
        followup_type: FOLLOWUP_1 or FOLLOWUP_2
        previous_followup: The first follow-up (for generating the second)
        
    Returns:
        dict with keys: subject, body
    """
    client = get_openai_client()

    # Select prompt
    if followup_type == EmailType.FOLLOWUP_1:
        system_prompt = FOLLOWUP_1_PROMPT
    else:
        system_prompt = FOLLOWUP_2_PROMPT

    # Build context — sanitize lead fields against prompt injection
    context = (
        f"Lead: {sanitize_input(lead.first_name)} {sanitize_input(lead.last_name)} at {sanitize_input(lead.company_name)}\n"
        f"Industry: {sanitize_input(lead.industry or 'Unknown')}\n\n"
        f"Original email subject: {original_email.subject}\n"
        f"Original email body:\n{original_email.body}\n"
    )

    if previous_followup and followup_type == EmailType.FOLLOWUP_2:
        context += (
            f"\nFirst follow-up body:\n{previous_followup.body}\n"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": context},
    ]

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=OPENAI_TEMPERATURE,
        max_tokens=300,
    )

    result = clean_json_response(response.choices[0].message.content)

    if "subject" not in result or "body" not in result:
        raise ValueError(f"Follow-up response missing keys: {result}")

    # Ensure Re: prefix
    if not result["subject"].startswith("Re:"):
        result["subject"] = f"Re: {original_email.subject}"

    # Spam check
    spam_found = check_spam_words(result["body"])
    if spam_found:
        logger.warning(f"Spam words in follow-up for {lead.email}: {spam_found}")

    # Add unsubscribe footer
    result["body"] = result["body"].rstrip() + UNSUBSCRIBE_FOOTER

    logger.info(
        f"Generated {followup_type.value} for {lead.email}: "
        f"subject='{result['subject']}'"
    )
    return result


def generate_followup_for_lead(
    lead_id: int,
    followup_type: EmailType,
) -> Optional[dict]:
    """
    Generate and store a follow-up email for a specific lead.
    
    Returns:
        dict with email details or None if failed/not applicable
    """
    with get_session() as session:
        lead = session.get(Lead, lead_id)
        if not lead:
            logger.error(f"Lead {lead_id} not found")
            return None

        # Don't follow up if replied, bounced, or unsubscribed
        if lead.status in (LeadStatus.REPLIED, LeadStatus.BOUNCED, LeadStatus.UNSUBSCRIBED):
            logger.info(f"Lead {lead_id} status is {lead.status.value}, skipping follow-up")
            return None

        # Get original email
        original = (
            session.query(EmailRecord)
            .filter_by(lead_id=lead_id, email_type=EmailType.INITIAL, status=EmailStatus.SENT)
            .first()
        )
        if not original:
            logger.warning(f"No sent initial email found for lead {lead_id}")
            return None

        # Get previous follow-up (for follow-up 2)
        previous_followup = None
        if followup_type == EmailType.FOLLOWUP_2:
            previous_followup = (
                session.query(EmailRecord)
                .filter_by(lead_id=lead_id, email_type=EmailType.FOLLOWUP_1, status=EmailStatus.SENT)
                .first()
            )

        # Check if this follow-up already exists
        existing = (
            session.query(EmailRecord)
            .filter_by(lead_id=lead_id, email_type=followup_type)
            .filter(EmailRecord.status.in_([EmailStatus.SENT, EmailStatus.PENDING, EmailStatus.QUEUED]))
            .first()
        )
        if existing:
            logger.info(f"{followup_type.value} already exists for lead {lead_id}")
            return None

        try:
            email_data = generate_followup(
                lead, original, followup_type, previous_followup
            )

            record = EmailRecord(
                lead_id=lead.id,
                subject=email_data["subject"],
                body=email_data["body"],
                email_type=followup_type,
                status=EmailStatus.PENDING,
                gmail_thread_id=original.gmail_thread_id,
            )
            session.add(record)

            return {
                "lead_id": lead.id,
                "email": lead.email,
                "subject": email_data["subject"],
                "body": email_data["body"],
                "followup_type": followup_type.value,
            }

        except Exception as e:
            logger.error(f"Failed to generate {followup_type.value} for lead {lead_id}: {e}")
            return None
