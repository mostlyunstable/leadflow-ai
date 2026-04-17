#!/usr/bin/env python3
"""
Quick script to connect a Gmail account to LeadFlow AI.
Run this directly in your terminal — it will open Google's sign-in page.

Usage:
    python3 add_gmail.py your_email@gmail.com
"""

import sys
import os

# Make sure we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from config.settings import GMAIL_CREDENTIALS_FILE, GMAIL_SCOPES, GMAIL_TOKEN_DIR
from pathlib import Path


def add_gmail_account(email: str):
    print(f"\n🔐 Connecting Gmail account: {email}")
    print("=" * 50)

    # Check credentials file exists
    if not os.path.exists(GMAIL_CREDENTIALS_FILE):
        print(f"❌ credentials.json not found at: {GMAIL_CREDENTIALS_FILE}")
        print("   Download it from Google Cloud Console → Credentials")
        return False

    # Set up token path
    Path(GMAIL_TOKEN_DIR).mkdir(parents=True, exist_ok=True)
    safe_name = email.replace("@", "_at_").replace(".", "_")
    token_path = os.path.join(GMAIL_TOKEN_DIR, f"token_{safe_name}.json")

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("❌ Missing packages. Run: pip install google-api-python-client google-auth-oauthlib")
        return False

    creds = None

    # Check for existing token
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)
        if creds and creds.valid:
            print(f"✅ Already authenticated! Token exists at {token_path}")
        elif creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token...")
            creds.refresh(Request())

    # Need new auth
    if not creds or not creds.valid:
        print("\n🌐 Opening Google sign-in in your browser...")
        print("   → Sign in with the Gmail account you want to use for sending")
        print("   → Click 'Allow' on all permission screens")
        print("   → If you see 'Google hasn't verified this app', click 'Advanced' → 'Go to LeadFlow'\n")

        flow = InstalledAppFlow.from_client_secrets_file(
            GMAIL_CREDENTIALS_FILE, GMAIL_SCOPES
        )
        creds = flow.run_local_server(
            port=9004,
            open_browser=True,
            prompt="consent",
            success_message="✅ Gmail connected to LeadFlow! You can close this browser tab now."
        )

        # Save token
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print(f"\n💾 Token saved to: {token_path}")

    # Verify it works
    print("\n🔍 Verifying connection...")
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    verified_email = profile.get("emailAddress", email)
    print(f"✅ Successfully connected: {verified_email}")
    print(f"   Messages in inbox: {profile.get('messagesTotal', 'N/A')}")

    # Register in database
    from database.database import init_db, get_session
    from database.models import GmailAccount
    from datetime import datetime, timezone

    init_db()
    with get_session() as session:
        existing = session.query(GmailAccount).filter_by(email=verified_email).first()
        if existing:
            existing.is_healthy = True
            existing.is_active = True
            existing.error_message = None
            existing.token_file = token_path
            print(f"🔄 Updated existing account record for {verified_email}")
        else:
            account = GmailAccount(
                email=verified_email,
                display_name=verified_email.split("@")[0],
                token_file=token_path,
                is_active=True,
                is_healthy=True,
                last_reset_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
            session.add(account)
            print(f"✨ Registered new account: {verified_email}")

    print(f"\n🎉 Done! {verified_email} is ready to send emails via LeadFlow AI.")
    print("   You can now go to your dashboard at http://localhost:8000")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        email = input("Enter your Gmail address: ").strip()
    else:
        email = sys.argv[1].strip()

    if not email or "@" not in email:
        print("❌ Please provide a valid email address")
        sys.exit(1)

    success = add_gmail_account(email)
    sys.exit(0 if success else 1)
