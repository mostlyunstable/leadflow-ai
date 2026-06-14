"""
Shared AI Utilities — Common functions used across AI engine modules.
Provides OpenAI client initialization, JSON response cleaning, input sanitization,
and spam word detection.
"""

import json
import logging
import re
from typing import Optional

from config.settings import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    SPAM_TRIGGER_WORDS,
)

logger = logging.getLogger(__name__)


def get_openai_client():
    """Initialize OpenAI client with configured API key and base URL."""
    if not OPENAI_API_KEY:
        raise ValueError(
            "OpenAI API key not configured. Set OPENAI_API_KEY in your .env file."
        )
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def sanitize_input(text: str) -> str:
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


def check_spam_words(text: str) -> list[str]:
    """Check text for spam trigger words. Returns list of found triggers."""
    text_lower = text.lower()
    found = []
    for word in SPAM_TRIGGER_WORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
            found.append(word)
    return found


def clean_json_response(text: str) -> dict:
    """Parse JSON from OpenAI response, handling markdown wrapping and malformed output."""
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
