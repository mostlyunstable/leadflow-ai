# LeadFlow AI — Cold Email Outreach System

AI-powered cold email outreach system that ingests leads, generates hyper-personalized emails, sends via Gmail API with deliverability safeguards, tracks replies, and automates intelligent follow-ups.

---

## Features

- **Lead Ingestion** — Import from CSV files or Google Sheets with automatic validation & deduplication
- **Lead Enrichment** — Scrape company websites and use AI to extract descriptions, industry, and key offerings
- **AI Personalization** — Generate unique, human-sounding cold emails with OpenAI (no generic templates)
- **Gmail API Integration** — Secure OAuth2 sending with support for multiple accounts
- **Smart Throttling** — Random delays (30-120s), daily limits, domain warmup
- **Automated Follow-Ups** — 2-day and 5-day follow-ups that reference the original email
- **Reply Detection** — Monitor inboxes, classify replies (interested/not interested/OOO/unsubscribe)
- **Performance Optimization** — Track which subject lines and first lines get the best reply rates
- **Premium Dashboard** — Dark-mode UI with real-time stats, pipeline visualization, and campaign controls

---

## Quick Start

### 1. Install Dependencies

```bash
cd "LEAD GENERATOR"
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your **OpenAI API key**:
```
OPENAI_API_KEY=sk-your-key-here
```

### 3. Set Up Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the **Gmail API**
4. Go to **APIs & Services → Credentials**
5. Create an **OAuth 2.0 Client ID** (Desktop application type)
6. Download the JSON and save as `config/credentials/credentials.json`

### 4. Run the Application

```bash
python main.py
```

Open your browser to **http://localhost:8000**

### 5. Add a Gmail Account

- Go to the **Accounts** tab in the dashboard
- Click **Add Account** and enter your Gmail address
- Complete the OAuth flow in the browser window that opens

---

## Usage Workflow

### Step 1: Import Leads
Upload a CSV file with columns: `First Name`, `Last Name`, `Email`, `Company Name`, `Website` (optional), `Industry` (optional)

### Step 2: Enrich Leads
Click **Enrich Leads** to scrape company websites and extract business intelligence.

### Step 3: Create a Campaign
Go to **Campaigns** → **New Campaign** → set name and daily send limit.

### Step 4: Generate Emails
Click **Generate Emails** — AI will create personalized emails for each lead.

### Step 5: Start Campaign
Click **Start** on your campaign. Emails send automatically with throttling.

### Step 6: Monitor
- **Overview** dashboard shows real-time stats
- **Replies** tab shows classified responses
- Follow-ups are queued automatically after 2 and 5 days

---

## Project Structure

```
LEAD GENERATOR/
├── main.py                      # Application entry point
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template
├── config/
│   ├── settings.py              # Central configuration
│   └── credentials/             # OAuth tokens & keys
├── database/
│   ├── models.py                # SQLAlchemy ORM models
│   └── database.py              # DB engine & sessions
├── modules/
│   ├── lead_ingestion/          # CSV & Sheets import
│   ├── lead_enrichment/         # Website scraping
│   ├── ai_engine/               # Email generation & optimization
│   ├── email_sender/            # Gmail API & batch sending
│   ├── reply_tracker/           # Inbox monitoring & classification
│   └── scheduler/               # Follow-up scheduling
├── api/
│   └── routes.py                # FastAPI endpoints
└── dashboard/
    ├── templates/index.html     # Dashboard UI
    └── static/                  # CSS & JavaScript
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/leads/upload-csv` | Upload CSV file |
| POST | `/api/leads/sync-sheets` | Import from Google Sheets |
| GET | `/api/leads` | List leads (with filters) |
| POST | `/api/leads/enrich` | Trigger lead enrichment |
| POST | `/api/emails/generate` | Generate AI emails |
| POST | `/api/campaigns/create` | Create campaign |
| POST | `/api/campaigns/{id}/start` | Start campaign |
| POST | `/api/campaigns/{id}/pause` | Pause campaign |
| GET | `/api/stats` | Dashboard statistics |
| GET | `/api/emails` | Email send log |
| GET | `/api/replies` | Reply log |
| POST | `/api/replies/check` | Check inboxes now |
| POST | `/api/accounts/add` | Add Gmail account |
| GET | `/api/accounts` | List accounts |

Full API docs available at `http://localhost:8000/docs`

---

## Scaling

### Multiple Gmail Accounts
Add multiple accounts via the dashboard. The system uses **round-robin rotation** to distribute sends across accounts.

### Domain Warmup
Enabled by default. Starts at 10 emails/day and increases by 5 each day until reaching your configured limit.

### Deploy to Production
```bash
# Run with production settings
DEBUG=false LOG_LEVEL=WARNING python main.py
```

For persistent deployment, use systemd, Docker, or a process manager like PM2.

---

## Deliverability Safeguards

| Feature | Default |
|---------|---------|
| Daily send limit | 50/account |
| Random delay | 30-120 seconds |
| Warmup | Start at 10, +5/day |
| Email format | Plain text only |
| Spam word filter | 100+ trigger words |
| Unsubscribe footer | Auto-appended |
| Bounce detection | Automatic |

---

## Configuration

All settings can be overridden via `.env`:

```bash
DAILY_SEND_LIMIT=50          # Max emails per account per day
MIN_DELAY_SECONDS=30         # Minimum delay between sends
MAX_DELAY_SECONDS=120        # Maximum delay between sends
FOLLOWUP_1_DAYS=2            # Days before first follow-up
FOLLOWUP_2_DAYS=5            # Days before second follow-up
WARMUP_ENABLED=true          # Enable warmup mode
WARMUP_START_LIMIT=10        # Starting daily limit during warmup
WARMUP_INCREMENT=5           # Daily increase during warmup
```

---

## License

Private — All rights reserved.
