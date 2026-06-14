# LeadFlow AI — Project Report

---

## 1. Executive Summary

LeadFlow AI is an AI-powered cold email outreach system that automates the entire email marketing pipeline — from lead ingestion to personalized email generation, sending, reply tracking, and follow-ups. It eliminates generic templates by using LLMs to write unique, human-sounding cold emails for each prospect.

---

## 2. Problem Statement

Cold email outreach suffers from three core problems:

1. **Personalization at scale** — Writing unique emails for hundreds of prospects is time-prohibitive
2. **Deliverability** — Emails land in spam without proper throttling, warmup, and content hygiene
3. **Follow-up management** — Manual tracking of who to follow up with and when is error-prone

LeadFlow AI solves all three.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    LeadFlow AI                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │   Lead   │→ │  Lead    │→ │   AI     │             │
│  │ Ingestion│  │Enrichment│  │ Engine   │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│       ↓              ↓             ↓                   │
│  ┌──────────────────────────────────────────┐          │
│  │              SQLite Database             │          │
│  └──────────────────────────────────────────┘          │
│       ↓              ↓             ↓                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │  Gmail   │  │  Reply   │  │Follow-Up │             │
│  │  Sender  │  │ Tracker  │  │Scheduler │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│                                                         │
│  ┌──────────────────────────────────────────┐          │
│  │         FastAPI + Dashboard UI           │          │
│  └──────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

---

## 4. Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Backend | Python + FastAPI | REST API server |
| Database | SQLite + SQLAlchemy | Lead, email, and campaign storage |
| AI Engine | NVIDIA NIM (Llama 3.1 70B) | Personalized email generation |
| Email Service | Gmail API (OAuth2) | Sending emails via Gmail |
| Web Scraping | BeautifulSoup4 | Company website enrichment |
| Scheduling | APScheduler | Background jobs (replies, follow-ups, warmup) |
| Frontend | HTML/CSS/JS | Dark-mode dashboard |

---

## 5. Core Modules

### 5.1 Lead Ingestion (`modules/lead_ingestion/`)

**Input:** CSV files or Google Sheets

**Process:**
- Parses CSV with columns: `First Name`, `Last Name`, `Email`, `Company Name`, `Website`, `Industry`
- Validates email format and required fields
- Deduplicates against existing leads
- Stores in SQLite with status `NEW`

**API Endpoints:**
- `POST /api/leads/upload-csv` — Upload CSV file
- `POST /api/leads/sync-sheets` — Import from Google Sheets
- `GET /api/leads` — List leads with filters

---

### 5.2 Lead Enrichment (`modules/lead_enrichment/`)

**Input:** Lead records with website URLs

**Process:**
- Scrapes company website using BeautifulSoup
- Extracts page content (title, meta description, body text)
- Uses AI to extract: company description, industry, key offerings
- Updates lead record with enrichment data

**Why it matters:** Enrichment data feeds the AI engine, enabling truly personalized emails that reference specific company details.

---

### 5.3 AI Email Generator (`modules/ai_engine/`)

**Input:** Lead data (name, company, industry, enrichment data)

**Process:**
1. Builds context prompt with lead information
2. Sends to LLM (Llama 3.1 70B via NVIDIA NIM)
3. Parses JSON response: `{subject, body}`
4. Checks for spam trigger words (100+ word list)
5. Regenerates if spam words detected
6. Appends unsubscribe footer
7. Stores as `EmailRecord` with status `PENDING`

**Email Quality Rules:**
- 120-150 words body length
- Conversational tone (not salesy)
- Specific observation about the company (no generic openers)
- No spam trigger words
- Soft CTA (question, not "schedule a call")
- Plain text only (no HTML)

**Optimization:** Tracks which subject lines and body patterns get the best reply rates. High-performing templates are used as inspiration for future generations.

---

### 5.4 Email Sender (`modules/email_sender/`)

**Input:** Pending `EmailRecord` entries

**Process:**
1. Queries pending emails for the campaign
2. Respects daily send limit (default: 50/account)
3. Round-robin rotation across multiple Gmail accounts
4. Sends via Gmail API with OAuth2 authentication
5. Random delays between sends (30-120 seconds)
6. Retry logic with exponential backoff (3 attempts)
7. Updates record status to `SENT` on success
8. Detects bounces automatically

**Deliverability Safeguards:**

| Feature | Default Value |
|---------|--------------|
| Daily send limit | 50/account |
| Random delay | 30-120 seconds |
| Warmup start | 10 emails/day |
| Warmup increment | +5/day |
| Email format | Plain text only |
| Spam word filter | 100+ triggers |
| Unsubscribe footer | Auto-appended |

---

### 5.5 Reply Tracker (`modules/reply_tracker/`)

**Input:** Gmail inbox messages

**Process:**
1. Polls Gmail API every 5 minutes (configurable)
2. Fetches new messages since last check
3. Matches replies to sent emails by thread ID
4. Classifies replies using AI:
   - `interested` — Positive response
   - `not_interested` — Declined
   - `out_of_office` — Auto-reply
   - `unsubscribe` — Opt-out request
   - `spam` — Spam report
   - `unknown` — Unclassified
5. Updates lead status accordingly

---

### 5.6 Follow-Up Scheduler (`modules/scheduler/`)

**Input:** Sent emails that haven't received a reply

**Process:**
1. Runs hourly via APScheduler
2. Checks leads with status `EMAILED`
3. Queues follow-up 1 after 2 days (configurable)
4. Queues follow-up 2 after 5 days (configurable)
5. Follow-up emails reference the original message
6. Stops follow-ups if lead replies

---

### 5.7 Domain Warmup

**Process:**
1. New campaigns start at 10 emails/day
2. Daily limit increases by 5 each day
3. Reaches configured maximum (default: 50)
4. Prevents spam flags on new domains

---

## 6. Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `leads` | Prospect information and status tracking |
| `email_records` | All generated and sent emails |
| `replies` | Classified incoming replies |
| `campaigns` | Campaign settings and statistics |
| `email_templates` | High-performing templates for optimization |
| `gmail_accounts` | OAuth tokens and send limits |

### Lead Status Flow

```
NEW → ENRICHED → EMAIL_GENERATED → EMAILED → FOLLOWUP_1_SENT → FOLLOWUP_2_SENT
                                        ↓              ↓               ↓
                                   REPLIED         REPLIED         REPLIED
                                   BOUNCED
                                   UNSUBSCRIBED
```

---

## 7. API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/leads/upload-csv` | Upload CSV file |
| POST | `/api/leads/sync-sheets` | Import from Google Sheets |
| GET | `/api/leads` | List leads (filters: status, campaign_id) |
| DELETE | `/api/leads/{id}` | Delete a lead |
| POST | `/api/leads/enrich` | Trigger enrichment (background) |
| POST | `/api/emails/generate` | Generate AI emails (background) |
| GET | `/api/emails` | List email records |
| POST | `/api/campaigns/create` | Create campaign |
| GET | `/api/campaigns` | List all campaigns |
| POST | `/api/campaigns/{id}/start` | Start sending |
| POST | `/api/campaigns/{id}/pause` | Pause sending |
| GET | `/api/stats` | Dashboard statistics |
| GET | `/api/replies` | List classified replies |
| POST | `/api/replies/check` | Trigger inbox check |
| POST | `/api/followups/check` | Queue follow-ups |
| POST | `/api/accounts/add` | Add Gmail account |
| GET | `/api/accounts` | List Gmail accounts |
| POST | `/api/accounts/health-check` | Check account health |

Full interactive docs: `http://localhost:8000/docs`

---

## 8. Dashboard Features

- **Overview** — Real-time stats: leads sent, replies, bounce rate, reply rate
- **Leads** — Upload CSV, filter by status, enrich, generate emails
- **Campaigns** — Create, start, pause campaigns with warmup tracking
- **Emails** — View all sent/pending/failed emails with details
- **Replies** — Classified responses with confidence scores
- **Accounts** — Manage multiple Gmail accounts, health checks

---

## 9. Usage Workflow

```
1. Import Leads     →  Upload CSV or sync Google Sheets
        ↓
2. Enrich Leads     →  Scrape websites, extract company info
        ↓
3. Create Campaign  →  Set name and daily send limit
        ↓
4. Generate Emails  →  AI writes personalized emails per lead
        ↓
5. Start Campaign   →  Emails send with throttling
        ↓
6. Monitor          →  Track replies, follow-ups, bounces
```

---

## 10. Configuration

All settings configurable via `.env`:

```bash
# AI
OPENAI_API_KEY=your-key
OPENAI_MODEL=meta/llama-3.1-70b-instruct

# Sending
DAILY_SEND_LIMIT=50
MIN_DELAY_SECONDS=30
MAX_DELAY_SECONDS=120

# Follow-ups
FOLLOWUP_1_DAYS=2
FOLLOWUP_2_DAYS=5

# Warmup
WARMUP_ENABLED=true
WARMUP_START_LIMIT=10
WARMUP_INCREMENT=5
```

---

## 11. Scaling

- **Multiple Gmail accounts** — Round-robin rotation distributes sends
- **Domain warmup** — Gradual increase prevents spam flags
- **Campaign isolation** — Each campaign tracks its own stats and limits
- **Background processing** — Enrichment, generation, and sending run asynchronously

---

## 12. Security

- OAuth2 for Gmail (no password storage)
- API key optional for dashboard access
- `.env` file for secrets (never committed)
- Spam word filtering prevents deliverability issues
- Unsubscribe footer for CAN-SPAM compliance

---

## 13. Known Limitations

1. SQLite — Single-writer, not suitable for high-concurrency production
2. No webhook support for real-time reply detection
3. AI generation rate-limited by LLM API
4. Gmail API quotas (250 emails/day free, 1000/day with Workspace)

---

*Report generated for LeadFlow AI v1.0.0*
