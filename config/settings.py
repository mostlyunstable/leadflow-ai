"""
Central Configuration — Cold Email Outreach System
All settings are loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env ────────────────────────────────────────────────────────────────
load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)
CREDENTIALS_DIR = BASE_DIR / "config" / "credentials"
CREDENTIALS_DIR.mkdir(exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR / 'outreach.db'}")

# ── OpenAI / NVIDIA NIM ──────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "meta/llama-3.1-70b-instruct") # Optimized for Nvidia by default
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.8"))

# ── Gmail API ────────────────────────────────────────────────────────────────
GMAIL_CREDENTIALS_FILE = os.getenv(
    "GMAIL_CREDENTIALS_FILE",
    str(CREDENTIALS_DIR / "credentials.json"),
)
GMAIL_TOKEN_DIR = os.getenv(
    "GMAIL_TOKEN_DIR",
    str(CREDENTIALS_DIR / "tokens"),
)
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# ── Google Sheets ────────────────────────────────────────────────────────────
SHEETS_SERVICE_ACCOUNT_FILE = os.getenv(
    "SHEETS_SERVICE_ACCOUNT_FILE",
    str(CREDENTIALS_DIR / "service_account.json"),
)

# ── Email Sending ────────────────────────────────────────────────────────────
DAILY_SEND_LIMIT = int(os.getenv("DAILY_SEND_LIMIT", "50"))
MIN_DELAY_SECONDS = int(os.getenv("MIN_DELAY_SECONDS", "30"))
MAX_DELAY_SECONDS = int(os.getenv("MAX_DELAY_SECONDS", "120"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
WARMUP_ENABLED = os.getenv("WARMUP_ENABLED", "true").lower() == "true"
WARMUP_START_LIMIT = int(os.getenv("WARMUP_START_LIMIT", "10"))
WARMUP_INCREMENT = int(os.getenv("WARMUP_INCREMENT", "5"))

# ── Follow-Up ────────────────────────────────────────────────────────────────
FOLLOWUP_1_DAYS = int(os.getenv("FOLLOWUP_1_DAYS", "2"))
FOLLOWUP_2_DAYS = int(os.getenv("FOLLOWUP_2_DAYS", "5"))

# ── Reply Monitoring ─────────────────────────────────────────────────────────
REPLY_CHECK_INTERVAL_MINUTES = int(os.getenv("REPLY_CHECK_INTERVAL_MINUTES", "5"))

# ── Scraping ─────────────────────────────────────────────────────────────────
SCRAPE_TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT", "10"))
SCRAPE_USER_AGENT = os.getenv(
    "SCRAPE_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)

# ── Server ───────────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

# ── Spam Trigger Words ───────────────────────────────────────────────────────
SPAM_TRIGGER_WORDS = [
    "act now", "action required", "apply now", "buy now", "call now",
    "click here", "click below", "congratulations", "dear friend",
    "discount", "double your", "earn money", "exclusive deal",
    "free", "guarantee", "income", "increase sales", "incredible deal",
    "limited time", "make money", "million dollars", "no cost",
    "no obligation", "offer expires", "once in a lifetime", "order now",
    "please read", "promise", "pure profit", "risk free",
    "satisfaction guaranteed", "special promotion", "this isn't spam",
    "unlimited", "urgent", "winner", "you have been selected",
    "100% free", "100% satisfied", "additional income", "be your own boss",
    "cash bonus", "cheap", "credit card", "direct email",
    "do it today", "don't delete", "don't hesitate", "earn extra cash",
    "easy terms", "eliminate debt", "extra cash", "fantastic deal",
    "fast cash", "financial freedom", "for free", "get it now",
    "get paid", "get started", "giving away", "great offer",
    "guaranteed", "have you been", "hidden charges", "home based",
    "hot deal", "hurry up", "important information", "instant",
    "investment", "join millions", "just $", "last chance",
    "lifetime", "limited offer", "lowest price", "luxury",
    "mass email", "miracle", "money back", "money making",
    "monthly payment", "name brand", "new customers only",
    "no catch", "no experience", "no fees", "no gimmick",
    "no investment", "no purchase necessary", "no questions asked",
    "no strings attached", "not junk", "now only", "obligation",
    "one hundred percent", "one time", "online biz", "open immediately",
    "opportunity", "opt in", "order status", "outstanding values",
    "pennies a day", "potential earnings", "prize", "profits",
    "promotional", "reach millions", "real thing", "remove",
    "requires initial investment", "reserves the right",
    "sale", "satisfaction", "save big", "save now",
    "score", "serious cash", "special deal", "subscribe",
    "substantial income", "supplies are limited", "take action",
    "terms and conditions", "the best", "this is not",
    "trial", "undeniable", "unsolicited", "visit our website",
    "we hate spam", "what are you waiting for", "while supplies last",
    "why pay more", "work from home", "you are a winner",
    "you won", "your income",
]

# ── Unsubscribe Footer ──────────────────────────────────────────────────────
UNSUBSCRIBE_FOOTER = os.getenv(
    "UNSUBSCRIBE_FOOTER",
    "\n\n---\nIf you'd prefer not to hear from me, just reply 'unsubscribe' and I'll remove you immediately.",
)

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
