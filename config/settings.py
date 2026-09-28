"""
Configuration settings module (Backward Compatibility & Core Settings Re-export).
All modern configuration is managed in `core.config.Settings`.
"""

from pathlib import Path
from core.config import settings, AppEnvironment

# ── Re-exported settings constants ───────────────────────────────────────────
BASE_DIR = settings.LOG_DIR.parent
DATABASE_URL = settings.DATABASE_URL
REDIS_URL = settings.REDIS_URL

# Sending Limits
DAILY_SEND_LIMIT = settings.DAILY_SEND_LIMIT
HOURLY_SEND_LIMIT = settings.HOURLY_SEND_LIMIT
MIN_DELAY_SECONDS = settings.MIN_DELAY_SECONDS
MAX_DELAY_SECONDS = settings.MAX_DELAY_SECONDS
MAX_RETRIES = settings.MAX_RETRIES

# Follow-Up & Reply Tracking
FOLLOWUP_1_DAYS = settings.FOLLOWUP_1_DAYS
FOLLOWUP_2_DAYS = settings.FOLLOWUP_2_DAYS
REPLY_CHECK_INTERVAL_MINUTES = settings.REPLY_CHECK_INTERVAL_MINUTES

# Scraping & Enrichment
SCRAPE_TIMEOUT = settings.SCRAPE_TIMEOUT
SCRAPE_USER_AGENT = settings.SCRAPE_USER_AGENT
SCRAPE_MAX_REDIRECTS = settings.SCRAPE_MAX_REDIRECTS
SCRAPE_MAX_CONTENT_LENGTH = settings.SCRAPE_MAX_CONTENT_LENGTH

# Server & Auth
HOST = settings.HOST
PORT = settings.PORT
DEBUG = settings.DEBUG
DASHBOARD_API_KEY = settings.DASHBOARD_API_KEY
CORS_ORIGINS = settings.CORS_ORIGINS
SECRET_KEY = settings.SECRET_KEY
ENCRYPTION_KEY = settings.ENCRYPTION_KEY

# Gmail OAuth
GMAIL_CREDENTIALS_FILE = settings.GMAIL_CREDENTIALS_FILE
GMAIL_SCOPES = settings.GMAIL_SCOPES
GMAIL_TOKEN_DIR = str(BASE_DIR / "config" / "credentials")

# AI Settings
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_BASE_URL = settings.OPENAI_BASE_URL
OPENAI_MODEL = settings.OPENAI_MODEL
OPENAI_TEMPERATURE = settings.OPENAI_TEMPERATURE
OPENAI_MAX_TOKENS = settings.OPENAI_MAX_TOKENS

# Footers & Linter
UNSUBSCRIBE_FOOTER = settings.UNSUBSCRIBE_FOOTER

# Content Quality / Risk Heuristics (formerly 'spam trigger words')
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

# Logging
LOG_LEVEL = settings.LOG_LEVEL
LOG_DIR = settings.LOG_DIR
LOG_MAX_BYTES = settings.LOG_MAX_BYTES
LOG_BACKUP_COUNT = settings.LOG_BACKUP_COUNT
