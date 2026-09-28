# LeadFlow AI — Enterprise Outbound Intelligence & Campaign Delivery Platform

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7+-DC382D.svg)](https://redis.io/)
[![Tests](https://img.shields.io/badge/tests-58%20passed%20(100%25)-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-gray.svg)](LICENSE)

An enterprise-grade, multi-tenant outbound intelligence and cold outreach platform built for durability, security, and real deliverability.

Unlike naive scripts that block web threads with `time.sleep()`, store plaintext credentials on disk, or blindly follow SSRF redirects, LeadFlow AI v2.0 is re-architected with **durable job queues, worker leases, fail-closed authentication, SSRF defenses, AES/Fernet encryption at rest, and an automated 58-test verification suite**.

---

## Key Capabilities

| Layer | Architecture & Production Guarantees |
| :--- | :--- |
| **Multi-Tenancy** | Strict `Organization` boundaries with composite unique constraints `(organization_id, email)` and role-based permissions (`owner`, `admin`, `member`). |
| **Durable Execution** | Distributed `SendJob` state machine (`PENDING` -> `QUEUED` -> `PROCESSING` -> `SENT`/`RETRY_WAIT`/`FAILED`) backed by atomic 60s worker leases and automatic crash recovery reapers. |
| **Idempotency** | Deterministic `idempotency_key` per outbound message. Network timeouts or mid-flight worker restarts never trigger duplicate email sends to prospects. |
| **Security & Cryptography** | All Google OAuth refresh tokens and SMTP secrets are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). Passwords use PBKDF2-HMAC-SHA256 (310,000 iterations). Fail-closed authentication. |
| **SSRF-Defended Enrichment** | Layered website analysis: pre-flight DNS IP resolution blocks RFC 1918 private subnets, loopbacks, and cloud metadata (`169.254.169.254`). Re-validates redirects at every hop. Automated headless browser fallback for JS shells. |
| **Sending Policy Engine** | Evidence-based deliverability gate: enforces hourly and daily sender caps, recipient suppression lists, inter-send pacing, and an automated bounce rate circuit breaker. |
| **Domain Health Diagnostics** | Live DNS queries for MX, SPF, and DMARC authentication records to audit sender domain readiness. |
| **AI Validation** | Pydantic-validated structured outputs with prompt-injection sanitization and content quality heuristics. |
| **Automated Testing** | 58 comprehensive tests covering unit, integration, API, multi-tenancy, contract, e2e, and failure/recovery scenarios. |

---

## Architecture Topology

```text
                          ┌───────────────────────────┐
                          │   Frontend SPA (UI)       │
                          └─────────────┬─────────────┘
                                        │ HTTPS / JWT / API-Key
                                        ▼
                          ┌───────────────────────────┐
                          │    FastAPI Gateway        │
                          ├───────────────────────────┤
                          │ • Fail-Closed Auth        │
                          │ • Tenant Context Resolver │
                          │ • Security Headers        │
                          └──────┬─────────────┬──────┘
                                 │             │
                Enqueue SendJobs │             │ Relational Data
                                 ▼             ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────────┐
│ Redis / Durable Job Queue            │  │ PostgreSQL 16 (Multi-Tenant)     │
├──────────────────────────────────────┤  ├──────────────────────────────────┤
│ • Worker Leases (60s lock)           │  │ • Organizations / Users / Leads  │
│ • Atomic Claims                      │  │ • Campaigns / SendJobs / Attempts│
│ • Crash Recovery Reaper              │  │ • Encrypted Credentials (Fernet) │
└──────────────────┬───────────────────┘  └──────────────────────────────────┘
                   │
                   │ Claim Job
                   ▼
┌──────────────────────────────────────┐
│ Standalone Campaign Workers          │
├──────────────────────────────────────┤
│ • Sending Policy Engine              │
│ • Bounce Rate Circuit Breakers       │
│ • Idempotent Dispatch                │
└──────┬───────────────────────┬───────┘
       │                       │
       ▼                       ▼
┌──────────────────────┐ ┌──────────────────────┐
│ EmailProvider        │ │ Layered Enrichment   │
├──────────────────────┤ ├──────────────────────┤
│ • GmailProvider      │ │ • SSRFSafeHTTPFetch  │
│ • SMTPProvider       │ │ • BrowserFallback    │
│ • MockEmailProvider  │ │ • Confidence Scorer  │
└──────────────────────┘ └──────────────────────┘
```

---

## Quick Start (Docker Compose)

The recommended production deployment runs FastAPI, PostgreSQL, Redis, and Campaign Workers in decoupled containers:

### 1. Clone & Configure Environment
```bash
git clone https://github.com/mostlyunstable/leadflow-ai.git
cd leadflow-ai
cp .env.example .env
```

Edit `.env` with production keys:
```bash
SECRET_KEY=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

### 2. Start Services
```bash
docker compose up -d --build
```

### 3. Verify Health & Open Dashboard
- Open **http://localhost:8000** in your browser.
- Health Check: `curl http://localhost:8000/health`
- Seeded Admin: `admin@leadflow.local` / `admin123456`

---

## Local Development & Testing

Run locally with Python 3.10+:

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations
alembic upgrade head

# 4. Run full test suite (58 tests)
pytest tests/ -v

# 5. Start development server
python main.py
```

---

## Documentation

Full architectural and operational guides are available in the [`docs/`](docs/) directory:

- [`docs/FINAL_ENGINEERING_REPORT.md`](docs/FINAL_ENGINEERING_REPORT.md) — Rebuild audit, before/after analysis, and verification evidence.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Comprehensive technical architecture specification.
- [`docs/SECURITY.md`](docs/SECURITY.md) — Threat model, SSRF defenses, and cryptography controls.
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Production Docker Compose and migration guide.
- [`docs/TESTING.md`](docs/TESTING.md) — Test architecture and test runbook.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — SRE monitoring, rate limit handling, and recovery procedures.
- [`docs/PRODUCTION_AUDIT.md`](docs/PRODUCTION_AUDIT.md) — Original forensic audit cataloging P0–P3 vulnerabilities.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
