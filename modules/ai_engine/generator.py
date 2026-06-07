"""
AI Email Generator — Creates hyper-personalized cold emails.
Generates subject lines, email bodies, and ensures deliverability compliance.
"""

import json
import logging
import re
from typing import Optional

from config.settings import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    OPENAI_MAX_TOKENS,
    SPAM_TRIGGER_WORDS,
    UNSUBSCRIBE_FOOTER,
    OPENAI_BASE_URL,
)
from database.database import get_session
from database.models import Lead, EmailRecord, EmailType, EmailStatus, LeadStatus

logger = logging.getLogger(__name__)


# ── System Prompts ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert cold email copywriter who writes emails that feel genuinely human.

RULES — follow every one:
1. Write EXACTLY 120-150 words (body only, not including subject)
2. Tone: conversational, warm, confident — like a smart peer, NOT a salesperson
3. Subject line: 3-7 words, curiosity-driven, lowercase okay, no clickbait
4. First line: Make a SPECIFIC observation about their company/product/industry — never generic
5. NEVER use these phrases:
   - "I came across your company"
   - "I hope this email finds you well"
   - "I wanted to reach out"
   - "I noticed that"
   - "As a [industry] leader"
   - "revolutionary" / "game-changing" / "cutting-edge"
6. Do NOT sound like a template
7. End with a soft CTA — question or suggestion, not "schedule a call"
8. No exclamation marks in subject line
9. No emoji
10. Write in plain text, no formatting or bullet points

Return ONLY a valid JSON object:
{"subject": "...", "body": "..."}"""


def _get_openai_client():
    """Initialize OpenAI client."""
    if not OPENAI_API_KEY:
        raise ValueError(
            "OpenAI API key not configured. Set OPENAI_API_KEY in your .env file."
        )
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def _sanitize_input(text: str) -> str:
    """Strip prompt-injection patterns from user-supplied fields."""
    if not text:
        return text
    patterns = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"you\s+are\s+now\s+",
        r"disregard\s+",
        r"system\s*:\s*",
        r"<\|im_start\|>",
        r"<\|im_end\|>",
        r"```",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    return text.strip()


def _check_spam_words(text: str) -> list[str]:
    """Check text for spam trigger words. Returns list of found triggers."""
    text_lower = text.lower()
    found = []
    for word in SPAM_TRIGGER_WORDS:
        # Use word-boundary regex to avoid false positives like "free" in "freedom"
        if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
            found.append(word)
    return found


def _clean_json_response(text: str) -> dict:
    """Parse JSON from OpenAI response, handling markdown wrapping."""
    text = text.strip()

    # Remove markdown code blocks
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON - find first { and last }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            # Replace literal newlines inside strings with escaped newlines (multi-pass)
            for _ in range(5):
                candidate = re.sub(
                    r'(?<="body":\s*")([^"]*)\n([^"]*)', r'\1\\n\2', candidate
                )
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Last resort: manually extract subject and body
                subject_match = re.search(r'"subject"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
                body_match = re.search(
                    r'"body"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL
                )
                if subject_match and body_match:
                    return {
                        "subject": subject_match.group(1),
                        "body": body_match.group(1).replace("\\n", "\n"),
                    }
        raise ValueError(f"Could not parse JSON from response: {text[:200]}")


def generate_email(
    lead: Lead,
    high_performing_examples: Optional[list[dict]] = None,
) -> dict:
    """
    Generate a personalized initial cold email for a lead.
    
    Args:
        lead: Lead model instance with enrichment data
        high_performing_examples: Optional list of high-performing email examples
        
    Returns:
        dict with keys: subject, body
    """
    client = _get_openai_client()

    # Build lead context — sanitize all user-supplied fields against prompt injection
    first_name = _sanitize_input(lead.first_name or "")
    last_name = _sanitize_input(lead.last_name or "")
    company_name = _sanitize_input(lead.company_name or "")

    context_parts = [
        f"Recipient: {first_name} {last_name}",
        f"Company: {company_name}",
    ]

    if lead.industry:
        context_parts.append(f"Industry: {_sanitize_input(lead.industry)}")
    if lead.company_description:
        context_parts.append(f"Company description: {_sanitize_input(lead.company_description)}")
    if lead.key_offering:
        context_parts.append(f"Key offering: {_sanitize_input(lead.key_offering)}")
    if lead.website:
        context_parts.append(f"Website: {lead.website}")

    lead_context = "\n".join(context_parts)

    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add high-performing examples if available
    if high_performing_examples:
        examples_text = "Here are examples of high-performing emails (use as inspiration, don't copy):\n\n"
        for ex in high_performing_examples[:3]:
            examples_text += f'Subject: {ex["subject"]}\nBody: {ex["body"]}\n\n'
        messages.append({"role": "user", "content": examples_text})
        messages.append({
            "role": "assistant",
            "content": "Got it. I'll use these as style inspiration while creating something unique.",
        })

    messages.append({
        "role": "user",
        "content": f"Write a cold outreach email for this lead:\n\n{lead_context}",
    })

    # Generate
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=OPENAI_TEMPERATURE,
        max_tokens=OPENAI_MAX_TOKENS,
    )

    result = _clean_json_response(response.choices[0].message.content)

    # Validate required keys
    if "subject" not in result or "body" not in result:
        raise ValueError(f"AI response missing required keys: {result}")

    # Check for spam words
    spam_found = _check_spam_words(result["subject"] + " " + result["body"])
    if spam_found:
        logger.warning(
            f"Spam trigger words found in email for {lead.email}: {spam_found}. "
            "Regenerating..."
        )
        # Retry once with explicit instruction
        messages.append({
            "role": "assistant",
            "content": json.dumps(result),
        })
        messages.append({
            "role": "user",
            "content": (
                f"This email contains spam trigger words: {', '.join(spam_found)}. "
                "Rewrite avoiding ALL of those words. Return only JSON."
            ),
        })
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
        )
        result = _clean_json_response(response.choices[0].message.content)

    # Append unsubscribe footer
    result["body"] = result["body"].rstrip() + UNSUBSCRIBE_FOOTER

    logger.info(f"Generated email for {lead.email}: subject='{result['subject']}'")
    return result


def generate_email_for_lead(lead_id: int, campaign_id: int = None) -> Optional[dict]:
    """
    Generate and store email for a specific lead.

    Returns:
        dict with email details or None if failed
    """
    with get_session() as session:
        lead = session.get(Lead, lead_id)
        if not lead:
            logger.error(f"Lead {lead_id} not found")
            return None

        if lead.status in (LeadStatus.EMAILED, LeadStatus.REPLIED, LeadStatus.BOUNCED):
            logger.info(f"Lead {lead_id} already processed, skipping")
            return None

        try:
            # Get high-performing examples
            from modules.ai_engine.optimizer import get_top_performing_templates
            examples = get_top_performing_templates(limit=3)
        except Exception:
            examples = None

        try:
            email_data = generate_email(lead, high_performing_examples=examples)

            # Store in database
            record = EmailRecord(
                lead_id=lead.id,
                subject=email_data["subject"],
                body=email_data["body"],
                email_type=EmailType.INITIAL,
                status=EmailStatus.PENDING,
            )
            session.add(record)
            lead.status = LeadStatus.EMAIL_GENERATED

            return {
                "lead_id": lead.id,
                "email": lead.email,
                "subject": email_data["subject"],
                "body": email_data["body"],
                "record_id": record.id,
            }

        except Exception as e:
            logger.error(f"Failed to generate email for lead {lead_id}: {e}")
            return None


def generate_emails_batch(
    lead_ids: list[int] = None,
    campaign_id: int = None,
    limit: int = 50,
) -> dict:
    """
    Generate emails for a batch of leads.
    
    Returns:
        dict with generation stats
    """
    with get_session() as session:
        query = session.query(Lead).filter(
            Lead.status.in_([LeadStatus.NEW, LeadStatus.ENRICHED])
        )
        if campaign_id:
            query = query.filter_by(campaign_id=campaign_id)
        if lead_ids:
            query = query.filter(Lead.id.in_(lead_ids))

        leads = query.limit(limit).all()
        target_ids = [lead.id for lead in leads]

    generated = 0
    failed = 0

    for lead_id in target_ids:
        result = generate_email_for_lead(lead_id, campaign_id)
        if result:
            generated += 1
        else:
            failed += 1

    return {
        "total": len(target_ids),
        "generated": generated,
        "failed": failed,
    }
