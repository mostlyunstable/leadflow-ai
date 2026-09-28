"""
LLM Provider Abstraction & Pydantic Structured Output Validation.
Guarantees:
1. Provider decoupling (OpenAI, NVIDIA NIM, Mock).
2. Strict Pydantic validation on all model responses.
3. Timeout, retry, and token-overflow handling.
4. No unparsed or malformed AI output can become trusted database state.
"""

import json
import logging
import re
from typing import Optional, Protocol, List, Dict, Any
from pydantic import BaseModel, Field, field_validator

from core.config import settings

logger = logging.getLogger("leadflow.ai")


# ── Structured Output Schemas (Pydantic) ─────────────────────────────────────

class GeneratedEmailOutput(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200, description="Curiosity-driven subject line")
    body: str = Field(..., min_length=20, max_length=3000, description="Personalized email body text")

    @field_validator("subject", mode="before")
    @classmethod
    def clean_subject(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().strip('"').strip("'")
            # Strip excessive punctuation
            v = re.sub(r'!+', '', v)
        return v

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return v


class ReplyClassificationOutput(BaseModel):
    classification: str = Field(..., description="One of: interested, not_interested, out_of_office, unsubscribe, spam, unknown")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="")

    @field_validator("classification", mode="before")
    @classmethod
    def normalize_classification(cls, v: str) -> str:
        v_str = str(v).lower().strip().replace(" ", "_").replace("-", "_")
        valid = {"interested", "not_interested", "out_of_office", "unsubscribe", "spam", "unknown"}
        if v_str not in valid:
            return "unknown"
        return v_str


# ── Provider Protocol ────────────────────────────────────────────────────────

class LLMProvider(Protocol):
    """Protocol for LLM generation and classification services."""

    def generate_email(self, messages: List[Dict[str, str]]) -> GeneratedEmailOutput:
        ...

    def classify_reply(self, reply_text: str) -> ReplyClassificationOutput:
        ...


# ── Concrete Implementations ─────────────────────────────────────────────────

class MockLLMProvider:
    """Mock LLM provider returning validated, deterministic responses for testing."""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def generate_email(self, messages: List[Dict[str, str]]) -> GeneratedEmailOutput:
        if self.should_fail:
            raise RuntimeError("Mock LLM simulated generation failure")

        return GeneratedEmailOutput(
            subject="quick question regarding your team",
            body="Hey, noticed your recent growth and wanted to see if exploring outbound automation would be relevant right now. What do you think?",
        )

    def classify_reply(self, reply_text: str) -> ReplyClassificationOutput:
        if self.should_fail:
            raise RuntimeError("Mock LLM simulated classification failure")

        lower = reply_text.lower()
        if "unsubscribe" in lower or "remove me" in lower:
            return ReplyClassificationOutput(
                classification="unsubscribe", confidence=0.95, reason="Explicit unsubscribe request"
            )
        elif any(w in lower for w in ["interested", "let's talk", "send more info", "demo", "schedule", "call"]):
            return ReplyClassificationOutput(
                classification="interested", confidence=0.9, reason="Expressed interest"
            )
        elif "not interested" in lower or "no thanks" in lower:
            return ReplyClassificationOutput(
                classification="not_interested", confidence=0.9, reason="Declined"
            )
        elif "out of office" in lower or "away from my desk" in lower:
            return ReplyClassificationOutput(
                classification="out_of_office", confidence=0.95, reason="Auto-reply"
            )
        return ReplyClassificationOutput(
            classification="unknown", confidence=0.5, reason="Unclear intent"
        )


class OpenAILLMProvider:
    """OpenAI / NVIDIA NIM LLM provider with Pydantic response parsing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.model = model or settings.OPENAI_MODEL
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")
        from openai import OpenAI
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
        )
        return self._client

    def generate_email(self, messages: List[Dict[str, str]]) -> GeneratedEmailOutput:
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=settings.OPENAI_TEMPERATURE,
                max_tokens=settings.OPENAI_MAX_TOKENS,
            )
            raw_text = response.choices[0].message.content or ""
            parsed = self._extract_json_dict(raw_text)
            return GeneratedEmailOutput(**parsed)
        except Exception as e:
            logger.error(f"LLM email generation failed: {e}")
            raise

    def classify_reply(self, reply_text: str) -> ReplyClassificationOutput:
        client = self._get_client()
        prompt = (
            "Classify this email reply into exactly one category: "
            "interested, not_interested, out_of_office, unsubscribe, spam, unknown.\n"
            "Return JSON: {\"classification\": \"...\", \"confidence\": 0.0-1.0, \"reason\": \"...\"}\n\n"
            f"Reply text:\n{reply_text[:1000]}"
        )
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=150,
            )
            raw_text = response.choices[0].message.content or ""
            parsed = self._extract_json_dict(raw_text)
            return ReplyClassificationOutput(**parsed)
        except Exception as e:
            logger.error(f"LLM reply classification failed: {e}")
            raise

    def _extract_json_dict(self, text: str) -> Dict[str, Any]:
        """Robustly parse JSON object from markdown-wrapped or raw text."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        return json.loads(text)


def get_llm_provider() -> LLMProvider:
    """Factory returning configured LLMProvider."""
    if settings.OPENAI_API_KEY:
        return OpenAILLMProvider()
    return MockLLMProvider()
