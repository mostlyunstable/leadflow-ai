"""
Reply Classifier — AI-powered classification of email replies.
Categories: interested, not_interested, out_of_office, unsubscribe, spam.
"""

import json
import logging
from typing import Optional

from config.settings import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL
from database.models import ReplyClassification

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """You are an email reply classifier for a sales outreach system.

Classify the reply into EXACTLY one of these categories:
- "interested" — Positive response, wants to learn more, asks questions, agrees to a call
- "not_interested" — Polite or direct decline, not the right time, not relevant
- "out_of_office" — Auto-reply, vacation, OOO, will be back on [date]
- "unsubscribe" — Asks to be removed, stop emailing, unsubscribe request
- "spam" — Irrelevant, promotional, auto-generated non-OOO response

Return ONLY a JSON object:
{"classification": "...", "confidence": 0.0-1.0, "reason": "brief explanation"}"""


def classify_reply(reply_body: str) -> tuple[ReplyClassification, float]:
    """
    Classify an email reply using AI.
    
    Args:
        reply_body: The text content of the reply
        
    Returns:
        Tuple of (classification, confidence_score)
    """
    # Try rule-based classification first (fast path)
    rule_result = _rule_based_classify(reply_body)
    if rule_result:
        return rule_result

    # Fall back to AI classification
    if not OPENAI_API_KEY:
        logger.warning("No OpenAI key — using rule-based classification only")
        return ReplyClassification.UNKNOWN, 0.5

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CLASSIFICATION_PROMPT},
                {"role": "user", "content": f"Classify this reply:\n\n{reply_body[:1000]}"},
            ],
            temperature=0.1,
            max_tokens=150,
        )

        result_text = response.choices[0].message.content.strip()

        # Clean markdown wrapping
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0]

        result = json.loads(result_text)

        classification_str = result.get("classification", "unknown")
        confidence = float(result.get("confidence", 0.5))

        # Map to enum
        classification_map = {
            "interested": ReplyClassification.INTERESTED,
            "not_interested": ReplyClassification.NOT_INTERESTED,
            "out_of_office": ReplyClassification.OUT_OF_OFFICE,
            "unsubscribe": ReplyClassification.UNSUBSCRIBE,
            "spam": ReplyClassification.SPAM,
        }

        classification = classification_map.get(
            classification_str, ReplyClassification.UNKNOWN
        )

        logger.info(
            f"AI classified reply as: {classification.value} "
            f"(confidence: {confidence:.2f}, reason: {result.get('reason', 'N/A')})"
        )

        return classification, confidence

    except Exception as e:
        logger.error(f"AI classification failed: {e}")
        return ReplyClassification.UNKNOWN, 0.3


def _rule_based_classify(
    reply_body: str,
) -> Optional[tuple[ReplyClassification, float]]:
    """
    Fast rule-based classification for obvious cases.
    Returns None if uncertain (should fall through to AI).
    """
    body_lower = reply_body.lower().strip()

    # Out of office detection (high confidence patterns)
    ooo_patterns = [
        "out of office",
        "out of the office",
        "on vacation",
        "on leave",
        "on holiday",
        "i am currently away",
        "i'm currently away",
        "auto-reply",
        "automatic reply",
        "autoreply",
        "i will be out",
        "i'll be out",
        "i am out",
        "i'm out of",
        "will return on",
        "be back on",
        "limited access to email",
    ]
    if any(pattern in body_lower for pattern in ooo_patterns):
        return ReplyClassification.OUT_OF_OFFICE, 0.95

    # Unsubscribe detection
    unsub_patterns = [
        "unsubscribe",
        "remove me",
        "stop emailing",
        "stop contacting",
        "don't contact",
        "do not contact",
        "don't email",
        "do not email",
        "take me off",
        "opt out",
        "no longer interested in receiving",
        "please remove",
        "stop sending",
    ]
    if any(pattern in body_lower for pattern in unsub_patterns):
        return ReplyClassification.UNSUBSCRIBE, 0.90

    # Very short positive replies
    short_positive = [
        "yes", "sure", "sounds good", "interested",
        "tell me more", "let's chat", "let's talk",
        "send me more info", "i'd like to learn more",
        "when can we talk", "book a call", "schedule a call",
    ]
    if len(body_lower) < 100:
        for phrase in short_positive:
            if phrase in body_lower:
                return ReplyClassification.INTERESTED, 0.85

    # Short negative replies
    short_negative = [
        "not interested",
        "no thanks",
        "no thank you",
        "pass",
        "not for us",
        "not a fit",
        "we're good",
        "we're all set",
        "don't need",
        "do not need",
    ]
    if len(body_lower) < 150:
        for phrase in short_negative:
            if phrase in body_lower:
                return ReplyClassification.NOT_INTERESTED, 0.85

    # If no clear pattern, return None → fall through to AI
    return None
