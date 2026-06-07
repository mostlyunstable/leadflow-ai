"""
Gmail API Client — Secure OAuth2 integration for sending and reading emails.
Handles token management, email construction, and inbox queries.
"""

import base64
import logging
import os
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from config.settings import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_DIR, GMAIL_SCOPES

logger = logging.getLogger(__name__)


def _ensure_token_dir():
    """Create token directory if it doesn't exist."""
    Path(GMAIL_TOKEN_DIR).mkdir(parents=True, exist_ok=True)


def _get_token_path(email: str) -> str:
    """Get the token file path for a Gmail account."""
    _ensure_token_dir()
    safe_name = email.replace("@", "_at_").replace(".", "_")
    # Prevent path traversal even after sanitization
    safe_name = safe_name.replace("/", "_").replace("\\", "_").replace("..", "_")
    return os.path.join(GMAIL_TOKEN_DIR, f"token_{safe_name}.json")


class GmailClient:
    """
    Gmail API wrapper with OAuth2 authentication.
    Each instance is tied to a specific Gmail account.
    """

    def __init__(self, account_email: str):
        self.account_email = account_email
        self.token_path = _get_token_path(account_email)
        self._service = None

    def authenticate(self) -> bool:
        """
        Authenticate with Gmail API using OAuth2.
        Will open browser for first-time auth.
        Returns True if successful.
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError(
                "Gmail API requires: google-api-python-client, "
                "google-auth-httplib2, google-auth-oauthlib. "
                "Install with: pip install google-api-python-client "
                "google-auth-httplib2 google-auth-oauthlib"
            )

        creds = None

        # Load existing token
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, GMAIL_SCOPES)

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info(f"Token refreshed for {self.account_email}")
                except Exception as e:
                    logger.warning(f"Token refresh failed for {self.account_email}: {e}")
                    # Delete stale token so we re-authenticate cleanly
                    creds = None
                    try:
                        os.remove(self.token_path)
                    except OSError:
                        pass

            if not creds:
                if not os.path.exists(GMAIL_CREDENTIALS_FILE):
                    raise FileNotFoundError(
                        f"Gmail OAuth credentials not found: {GMAIL_CREDENTIALS_FILE}\n"
                        "Download from Google Cloud Console → APIs & Services → Credentials"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    GMAIL_CREDENTIALS_FILE, GMAIL_SCOPES
                )

                # Try browser-based auth first; fall back to console for headless environments
                try:
                    creds = flow.run_local_server(
                        port=8090,
                        open_browser=True,
                        prompt="consent",
                        success_message="Gmail connected to LeadFlow! You can close this tab.",
                    )
                except Exception:
                    logger.info("Browser auth unavailable, falling back to console OAuth")
                    creds = flow.run_console()

            # Save token
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())
            logger.info(f"Token saved for {self.account_email}")

        self._service = build("gmail", "v1", credentials=creds)
        logger.info(f"Gmail API authenticated for {self.account_email}")
        return True

    @property
    def service(self):
        """Get authenticated Gmail service, auto-authenticating if needed."""
        if self._service is None:
            self.authenticate()
        return self._service

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        sender_name: str = None,
    ) -> dict:
        """
        Send a plain-text email via Gmail API.

        Args:
            to: Recipient email
            subject: Email subject
            body: Email body (plain text)
            thread_id: Optional thread ID for follow-ups
            sender_name: Optional display name for From header

        Returns:
            dict with keys: message_id, thread_id, label_ids
        """
        # Construct email
        message = MIMEText(body, "plain")
        message["to"] = to
        message["subject"] = subject

        # From header with display name
        if sender_name:
            message["from"] = f"{sender_name} <{self.account_email}>"
        else:
            message["from"] = self.account_email

        # RFC 8058 One-Click List-Unsubscribe
        message["List-Unsubscribe"] = f"<mailto:{self.account_email}?subject=unsubscribe>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        # Encode
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        send_body = {"raw": raw}

        # Thread for follow-ups
        if thread_id:
            send_body["threadId"] = thread_id

        try:
            sent = (
                self.service.users()
                .messages()
                .send(userId="me", body=send_body)
                .execute()
            )

            result = {
                "message_id": sent.get("id"),
                "thread_id": sent.get("threadId"),
                "label_ids": sent.get("labelIds", []),
            }

            logger.info(f"Email sent to {to}: message_id={result['message_id']}")
            return result

        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            raise

    def get_messages(
        self,
        query: str = "is:inbox is:unread",
        max_results: int = 50,
    ) -> list[dict]:
        """
        List messages matching a query.
        
        Args:
            query: Gmail search query
            max_results: Max messages to return
            
        Returns:
            List of message metadata dicts
        """
        try:
            response = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            return response.get("messages", [])
        except Exception as e:
            logger.error(f"Failed to list messages: {e}")
            return []

    def get_message_detail(self, message_id: str) -> Optional[dict]:
        """
        Get full message details including body.
        
        Returns:
            dict with keys: id, thread_id, from, to, subject, body, date
        """
        try:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}

            # Extract body
            body = ""
            payload = msg["payload"]

            if "parts" in payload:
                for part in payload["parts"]:
                    if part["mimeType"] == "text/plain" and part.get("body", {}).get("data"):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        break
            elif payload.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")

            return {
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", ""),
                "body": body,
                "date": headers.get("date", ""),
                "label_ids": msg.get("labelIds", []),
            }

        except Exception as e:
            logger.error(f"Failed to get message {message_id}: {e}")
            return None

    def get_thread_messages(self, thread_id: str) -> list[dict]:
        """Get all messages in a thread."""
        try:
            thread = (
                self.service.users()
                .threads()
                .get(userId="me", id=thread_id)
                .execute()
            )
            messages = []
            for msg in thread.get("messages", []):
                detail = self.get_message_detail(msg["id"])
                if detail:
                    messages.append(detail)
            return messages
        except Exception as e:
            logger.error(f"Failed to get thread {thread_id}: {e}")
            return []

    def mark_as_read(self, message_id: str):
        """Mark a message as read."""
        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        except Exception as e:
            logger.error(f"Failed to mark message {message_id} as read: {e}")

    def check_health(self) -> bool:
        """Check if the Gmail connection is healthy."""
        try:
            self.service.users().getProfile(userId="me").execute()
            return True
        except Exception as e:
            logger.error(f"Gmail health check failed for {self.account_email}: {e}")
            return False
