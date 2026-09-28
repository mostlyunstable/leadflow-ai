"""
Email Provider Abstraction Layer.
Defines clean protocols and data transfer objects for email delivery.
Decouples campaign logic from concrete third-party providers (Gmail, SMTP, Mock).
"""

from dataclasses import dataclass
from typing import Optional, Protocol, Dict, Any, List
import logging

logger = logging.getLogger("leadflow.provider")


import enum
from enum import Enum


class ProviderErrorCode(str, Enum):
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    UNKNOWN = "UNKNOWN"


@dataclass
class OutboundMessage:
    """Standardized outbound email message payload."""
    to_email: str
    from_email: str
    subject: str
    body_text: str
    body_html: Optional[str] = None
    idempotency_key: str = ""
    thread_id: Optional[str] = None
    reply_to: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    organization_id: Optional[int] = None
    campaign_id: Optional[int] = None
    lead_id: Optional[int] = None


@dataclass
class SendResult:
    """Standardized result of a provider send operation."""
    success: bool
    provider_message_id: Optional[str] = None
    provider_thread_id: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    error_category: Optional[ProviderErrorCode] = None
    retryable: bool = False
    raw_response: Optional[Dict[str, Any]] = None


class EmailProvider(Protocol):
    """Protocol defining the email provider contract."""

    @property
    def provider_name(self) -> str:
        ...

    def send(self, message: OutboundMessage) -> SendResult:
        """Deliver an outbound message. Must be synchronous or awaited by caller."""
        ...

    def verify_account(self) -> bool:
        """Verify provider authentication and connection health."""
        ...


# ── Concrete Provider Implementations ────────────────────────────────────────

class MockEmailProvider:
    """
    Mock email provider for automated testing, development, and dry runs.
    Records all sent messages in memory with deterministic responses.
    """

    def __init__(self, should_fail: bool = False, retryable_error: bool = False):
        self.should_fail = should_fail
        self.retryable_error = retryable_error
        self.sent_messages: List[OutboundMessage] = []
        self._provider_name = "mock"

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def send(self, message: OutboundMessage) -> SendResult:
        if self.should_fail:
            return SendResult(
                success=False,
                error_message="Mock provider simulated failure",
                error_code="MOCK_FAILURE",
                retryable=self.retryable_error,
            )

        self.sent_messages.append(message)
        msg_id = f"mock-msg-{len(self.sent_messages)}-{hash(message.idempotency_key) & 0xffffffff:x}"
        thread_id = message.thread_id or f"mock-thd-{hash(message.to_email) & 0xffff:x}"

        logger.info(f"[MockProvider] Sent email to {message.to_email} (id={msg_id})")
        return SendResult(
            success=True,
            provider_message_id=msg_id,
            provider_thread_id=thread_id,
            raw_response={"status": "sent", "provider": "mock"},
        )

    def simulate_failure(self, message: OutboundMessage, failure_type: str) -> SendResult:
        """Simulate specific provider failure modes for test verification."""
        if failure_type == "rate_limit":
            return SendResult(
                success=False,
                error_message="429 Too Many Requests (Rate limit exceeded)",
                error_code="429",
                error_category=ProviderErrorCode.RATE_LIMIT,
                retryable=True,
            )
        elif failure_type == "server_error":
            return SendResult(
                success=False,
                error_message="500 Internal Server Error (Temporary)",
                error_code="500",
                error_category=ProviderErrorCode.TEMPORARY_FAILURE,
                retryable=True,
            )
        elif failure_type == "auth_error":
            return SendResult(
                success=False,
                error_message="401 Unauthorized (Invalid credentials / Revoked token)",
                error_code="401",
                error_category=ProviderErrorCode.AUTH_ERROR,
                retryable=False,
            )
        elif failure_type == "permanent_bounce":
            return SendResult(
                success=False,
                error_message="550 5.1.1 User unknown / Permanent mailbox bounce",
                error_code="550",
                error_category=ProviderErrorCode.PERMANENT_FAILURE,
                retryable=False,
            )
        else:
            return SendResult(
                success=False,
                error_message=f"Simulated unknown failure: {failure_type}",
                error_code="UNKNOWN",
                error_category=ProviderErrorCode.UNKNOWN,
                retryable=True,
            )

    def verify_account(self) -> bool:
        return not self.should_fail


class GmailProvider:
    """
    Gmail API implementation of EmailProvider.
    Uses decrypted OAuth2 credentials and the official Google API client.
    """

    def __init__(self, account_email: str, credentials_json: str):
        self.account_email = account_email
        self.credentials_json = credentials_json
        self._provider_name = "gmail"
        self._service = None

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def _get_service(self):
        """Build Google API service using credentials."""
        if self._service is not None:
            return self._service

        import json
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = json.loads(self.credentials_json)
        credentials = Credentials.from_authorized_user_info(creds_data)
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return self._service

    def send(self, message: OutboundMessage) -> SendResult:
        import base64
        from email.mime.text import MIMEText
        from googleapiclient.errors import HttpError

        try:
            service = self._get_service()
            msg = MIMEText(message.body_text)
            msg["to"] = message.to_email
            msg["from"] = self.account_email
            msg["subject"] = message.subject

            # RFC 8058 One-Click Unsubscribe headers
            if message.headers:
                for k, v in message.headers.items():
                    msg[k] = v

            body_payload: Dict[str, Any] = {
                "raw": base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            }
            if message.thread_id:
                body_payload["threadId"] = message.thread_id

            response = service.users().messages().send(userId="me", body=body_payload).execute()

            return SendResult(
                success=True,
                provider_message_id=response.get("id"),
                provider_thread_id=response.get("threadId"),
                raw_response=response,
            )

        except HttpError as e:
            status = e.resp.status if hasattr(e, "resp") else 500
            retryable = status in (429, 500, 502, 503, 504)
            logger.error(f"Gmail API HTTP error {status} sending to {message.to_email}: {e}")
            return SendResult(
                success=False,
                error_message=str(e),
                error_code=f"GMAIL_HTTP_{status}",
                retryable=retryable,
            )
        except Exception as e:
            logger.error(f"Unexpected error sending via Gmail to {message.to_email}: {e}")
            return SendResult(
                success=False,
                error_message=str(e),
                error_code="GMAIL_CLIENT_ERROR",
                retryable=True,  # Transient network drop is retryable with idempotency check
            )

    def verify_account(self) -> bool:
        try:
            service = self._get_service()
            profile = service.users().getProfile(userId="me").execute()
            return profile.get("emailAddress", "").lower() == self.account_email.lower()
        except Exception as e:
            logger.error(f"Gmail verification failed for {self.account_email}: {e}")
            return False
