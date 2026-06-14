<p align="center">
  <h1 align="center">LeadFlow AI</h1>
  <p align="center">AI-Powered Cold Email Outreach System</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python">
    <img src="https://img.shields.io/badge/fastapi-0.104+-green" alt="FastAPI">
    <img src="https://img.shields.io/badge/sqlalchemy-2.0+-orange" alt="SQLAlchemy">
    <img src="https://img.shields.io/badge/license-MIT-gray" alt="License">
  </p>
</p>

---

A complete cold email outreach platform that ingests leads, generates hyper-personalized emails with AI, sends via Gmail API with deliverability safeguards, tracks replies, and automates intelligent follow-ups.

## Features

| Category | Capability |
|----------|-----------|
| **Lead Ingestion** | Import from CSV or Google Sheets with validation, deduplication, and flexible column mapping |
| **Lead Enrichment** | Scrape company websites + AI summarization for industry, description, and key offering |
| **AI Email Generation** | Personalized cold emails using Llama 3.1 70B (NVIDIA NIM) with spam word detection |
| **Gmail Integration** | OAuth2 sending with RFC 8058 List-Unsubscribe headers, multi-account round-robin |
| **Smart Throttling** | Random delays (30-120s), warmup-aware daily limits, exponential backoff retry |
| **Automated Follow-Ups** | 2-day (new angle) and 5-day (breakup) follow-ups threaded via Gmail thread ID |
| **Reply Tracking** | Inbox polling, AI + rule-based classification (interested / not interested / OOO / unsubscribe) |
| **Performance Optimization** | Template performance scoring feeds best patterns back to AI generation |
| **Dashboard** | Dark-mode SPA with real-time stats, pipeline breakdown, campaign controls |

## Tech Stack

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy 2.0, APScheduler
- **Database:** SQLite (WAL mode) — production-ready for single-node; swap to PostgreSQL for multi-node
- **AI:** NVIDIA NIM (Llama 3.1 70B Instruct) via OpenAI-compatible API
- **Email:** Gmail API (OAuth2) with round-robin multi-account support
- **Frontend:** Vanilla JS SPA, CSS custom properties, no build step required

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/mostlyunstable/leadflow-ai.git
cd leadflow-ai
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your API key:

```bash
OPENAI_API_KEY=nvapi-your-key-here
OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1
OPENAI_MODEL=meta/llama-3.1-70b-instruct
```

### 3. Set Up Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Gmail API**
3. Go to **APIs & Services > Credentials**
4. Create an **OAuth 2.0 Client ID** (Desktop application)
5. Download the JSON and save as `config/credentials/credentials.json`

### 4. Run

```bash
python main.py
```

Open **http://localhost:8000** in your browser.

### 5. Connect Gmail

Go to **Accounts** tab > **Add Account** > complete the OAuth flow.

## Usage Workflow

```
CSV Import  ──>  Enrich Leads  ──>  Generate Emails  ──>  Start Campaign
                                                         │
              ┌──────────────────────────────────────────┘
              ▼
         Send Emails  ──>  Track Replies  ──>  Auto Follow-Ups
         (throttled)       (AI classified)     (2-day, 5-day)
```

1. **Import Leads** — Upload a CSV with columns: `first_name`, `last_name`, `email`, `company_name`, `website` (optional), `industry` (optional)
2. **Enrich Leads** — Click **Enrich Leads** to scrape company websites and extract business context
3. **Create Campaign** — Go to **Campaigns** > **New Campaign** > set name and daily send limit
4. **Generate Emails** — Click **Generate Emails** — AI creates personalized emails for each lead
5. **Start Campaign** — Click **Start** on your campaign. Emails send automatically with throttling
6. **Monitor** — Overview dashboard shows real-time stats; Replies tab shows classified responses; follow-ups queue automatically

## Project Structure

```
leadflow-ai/
├── main.py                          # FastAPI entrypoint, scheduler, lifespan
├── config/
│   ├── settings.py                  # All config from env vars
│   └── credentials/                 # OAuth tokens (gitignored)
├── database/
│   ├── database.py                  # SQLAlchemy engine, sessions
│   └── models.py                    # 6 tables: leads, email_records, replies,
│                                    #   campaigns, email_templates, gmail_accounts
├── api/
│   └── routes.py                    # ~17 REST endpoints
├── modules/
│   ├── ai_engine/
│   │   ├── ai_utils.py              # Shared: OpenAI client, JSON parsing, sanitization
│   │   ├── generator.py             # Cold email generation
│   │   ├── followup_generator.py    # Follow-up generation (FU-1, FU-2)
│   │   └── optimizer.py             # Template performance tracking
│   ├── email_sender/
│   │   ├── gmail_client.py          # Gmail OAuth2 client
│   │   ├── account_manager.py       # Multi-account round-robin
│   │   └── batch_sender.py          # Throttled batch sending
│   ├── lead_ingestion/
│   │   ├── csv_handler.py           # CSV parsing with flexible column mapping
│   │   ├── sheets_handler.py        # Google Sheets import
│   │   └── validator.py             # Email validation, dedup, disposable detection
│   ├── lead_enrichment/
│   │   └── enricher.py              # Website scraping + AI summarization
│   ├── reply_tracker/
│   │   ├── monitor.py               # Inbox polling, bounce detection
│   │   └── classifier.py            # Rule-based + AI reply classification
│   └── scheduler/
│       └── followup_scheduler.py    # Automated follow-up timing
├── dashboard/
│   ├── templates/index.html         # SPA dashboard
│   └── static/
│       ├── css/styles.css           # Dark theme, responsive
│       └── js/dashboard.js          # All UI interactions
└── alembic/                         # Database migrations (placeholder)
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/leads/upload-csv` | Upload CSV of leads |
| `POST` | `/api/leads/sync-sheets` | Import from Google Sheets |
| `GET` | `/api/leads` | List leads (filter by status, campaign) |
| `DELETE` | `/api/leads/{id}` | Delete a lead |
| `POST` | `/api/leads/enrich` | Trigger enrichment (background) |
| `POST` | `/api/emails/generate` | Generate AI emails (background) |
| `GET` | `/api/emails` | List email records (filter by status, type) |
| `POST` | `/api/campaigns/create` | Create a campaign |
| `GET` | `/api/campaigns` | List all campaigns |
| `POST` | `/api/campaigns/{id}/start` | Start sending |
| `POST` | `/api/campaigns/{id}/pause` | Pause sending |
| `GET` | `/api/replies` | List replies (filter by classification) |
| `POST` | `/api/replies/check` | Trigger inbox check (background) |
| `POST` | `/api/followups/check` | Queue eligible follow-ups |
| `GET` | `/api/followups/status` | Follow-up pipeline status |
| `POST` | `/api/accounts/add` | Add Gmail account (OAuth) |
| `GET` | `/api/accounts` | List Gmail accounts |
| `POST` | `/api/accounts/health-check` | Run health check |
| `GET` | `/api/stats` | Dashboard statistics |
| `GET` | `/api/stats/optimization` | Email optimization insights |

Interactive API docs at **http://localhost:8000/docs**

## Configuration

All settings are configurable via environment variables or `.env`:

```bash
# ── AI ──────────────────────────────────────
OPENAI_API_KEY=                    # NVIDIA NIM / OpenAI API key
OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1
OPENAI_MODEL=meta/llama-3.1-70b-instruct
OPENAI_MAX_TOKENS=500
OPENAI_TEMPERATURE=0.8

# ── Email Sending ───────────────────────────
DAILY_SEND_LIMIT=50                # Max emails per account per day
MIN_DELAY_SECONDS=30               # Minimum delay between sends
MAX_DELAY_SECONDS=120              # Maximum delay between sends
MAX_RETRIES=3                      # Retry attempts per email

# ── Warmup ──────────────────────────────────
WARMUP_ENABLED=true
WARMUP_START_LIMIT=10              # Starting daily limit
WARMUP_INCREMENT=5                 # Daily increase

# ── Follow-Ups ──────────────────────────────
FOLLOWUP_1_DAYS=2                  # Days before first follow-up
FOLLOWUP_2_DAYS=5                  # Days before second follow-up

# ── Reply Monitoring ────────────────────────
REPLY_CHECK_INTERVAL_MINUTES=5     # Inbox poll frequency

# ── Scraping ────────────────────────────────
SCRAPE_TIMEOUT=10                  # Website scrape timeout (seconds)

# ── Server ──────────────────────────────────
HOST=0.0.0.0
PORT=8000
DEBUG=true
DASHBOARD_API_KEY=                 # Set to require API key auth
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

# ── Logging ─────────────────────────────────
LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760             # 10 MB per log file
LOG_BACKUP_COUNT=5                 # Number of rotated log files
```

## Deliverability Safeguards

| Feature | Implementation |
|---------|---------------|
| Daily send limits | Per-account, warmup-aware (starts at 10, +5/day) |
| Random delays | 30-120 seconds between sends |
| Exponential backoff | 2^attempt + jitter on failures |
| Email format | Plain text only (higher deliverability) |
| Spam filter | 120+ trigger words checked before sending |
| Unsubscribe | RFC 8058 One-Click List-Unsubscribe header + footer |
| Bounce detection | Automatic via inbox polling |
| Multi-account | Round-robin rotation across connected accounts |

## Architecture

```
CSV/Sheets ──> Lead Import ──> Enrichment ──> AI Generation ──> Gmail Send
                  │                                              │
                  ▼                                              ▼
              SQLite DB ─────────────────────────────────── Reply Tracking
                  │                                              │
                  ▼                                              ▼
             Dashboard  <────────────────────── Classification (AI + Rules)
                                                         │
                                                         ▼
                                                   Follow-Up Scheduler
                                                   (2-day, 5-day)
```

## License

Private — All rights reserved.
