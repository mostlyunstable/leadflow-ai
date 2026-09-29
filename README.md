# LeadFlow AI — Enterprise Outbound Intelligence & Campaign Delivery Platform

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7+-DC382D.svg)](https://redis.io/)
[![Automated Tests](https://img.shields.io/badge/tests-79%20passed%20(100%25)-brightgreen.svg)]()
[![VPS Production Validation](https://img.shields.io/badge/vps%20validation-32%20passed%20(100%25)-success.svg)]()
[![Production Benchmark](https://img.shields.io/badge/load%20test-458%20req%2Fs%20(0%20errors)-blueviolet.svg)]()
[![License](https://img.shields.io/badge/license-MIT-gray.svg)](LICENSE)

An enterprise-grade, multi-tenant outbound intelligence and cold outreach platform built for durability, security, and deliverability under real operating conditions.

Unlike prototypes that rely on in-memory state, unencrypted OAuth credentials, single-worker thread locks, or unconstrained headless browsers, LeadFlow AI is an audited, **zero-Docker native Linux system** supervised by **systemd**, terminated by **Nginx HTTPS**, and backed by **PostgreSQL 16** with atomic leases, **Redis 7** graceful degradation, and **79 automated + 32 real VPS tests passing**.

---

## Key Capabilities & Production Guarantees

| Component | Production Architecture & Operational Guarantees |
| :--- | :--- |
| **Native Linux Model** | 100% native Linux process supervision via systemd (`leadflow-api`, `campaign-worker`, `enrichment-worker`, `maintenance-worker`). Zero Docker overhead. |
| **Multi-Tenancy & RBAC** | Strict `Organization` tenant isolation across all 18 database tables. Composite uniqueness `(organization_id, email)`. Fail-closed role enforcement (`owner`, `admin`, `member`, `viewer`). |
| **Durable Execution** | Distributed `SendJob` state machine (`PENDING` -> `QUEUED` -> `PROCESSING` -> `SENT`/`RETRY_WAIT`/`FAILED`). Atomic leases with PostgreSQL `FOR UPDATE SKIP LOCKED` and automated crash recovery reapers. |
| **Message Idempotency** | Deterministic `idempotency_key` per outbound message. Network timeouts or mid-flight worker kills never duplicate prospect emails. |
| **Security & Cryptography** | OAuth refresh tokens and SMTP credentials encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). Passwords hashed using PBKDF2-HMAC-SHA256 (310,000 rounds). Redaction masks secrets from application logs. |
| **SSRF-Defended Enrichment** | Pre-flight DNS validation strictly blocks RFC 1918 subnets, loopback interfaces, and cloud metadata endpoints (`169.254.169.254`). Re-validates redirects per hop. Headless Chromium capacity bounded via `BoundedSemaphore(3)`. |
| **Deliverability Engine** | Enforces hourly/daily account caps, suppression lists, inter-send jitter, and an automatic bounce rate circuit breaker. Validates MX, SPF, and DMARC records via live DNS checks. |
| **Disaster Recovery** | Verified physical backup (`backup.sh` in 249ms) and live restore (`restore.sh` in 966ms RTO) with SHA-256 integrity checksums. |
| **Observability** | Prometheus `/metrics` endpoint exposing real-time queue depth, active database connections, and HTTP status counters. |

---

## Production Architecture Topology

```text
                               Internet
                                  │
                                  ▼
                     ┌─────────────────────────┐
                     │       Nginx 1.24        │
                     │  • HTTPS Termination    │
                     │  • Modern TLS Ciphers   │
                     │  • Security Headers     │
                     │  • Rate Limiting        │
                     └────────────┬────────────┘
                                  │ Reverse Proxy
                                  ▼
                     ┌─────────────────────────┐
                     │    FastAPI / Uvicorn    │ (4 Workers, Systemd)
                     │  • Fail-Closed Auth     │
                     │  • Tenant Isolation     │
                     │  • /health & /metrics   │
                     └──────┬───────────┬──────┘
                            │           │
           Enqueue SendJobs │           │ Relational Queries & Leases
                            ▼           ▼
       ┌────────────────────────┐  ┌──────────────────────────────────┐
       │ Redis 7 Server         │  │ PostgreSQL 16 (Multi-Tenant)     │
       ├────────────────────────┤  ├──────────────────────────────────┤
       │ • Fast locks & cache   │  │ • 18 Migrated Production Tables  │
       │ • Graceful degradation │  │ • FOR UPDATE SKIP LOCKED leases  │
       │ • Standalone service   │  │ • Encrypted Credentials (Fernet) │
       └────────────────────────┘  └──────────────────┬───────────────┘
                                                      │
                       ┌──────────────────────────────┼──────────────────────────────┐
                       │ Atomic Lease Claim           │ Bounded Scrape Task          │ Reaper & Retention
                       ▼                              ▼                              ▼
        ┌─────────────────────────────┐┌─────────────────────────────┐┌─────────────────────────────┐
        │  leadflow-campaign-worker   ││  leadflow-enrichment-worker ││ leadflow-maintenance-worker │
        ├─────────────────────────────┤├─────────────────────────────┤├─────────────────────────────┤
        │ • Policy Engine Check       ││ • SSRF-Safe HTTP Fetch      ││ • Crash Recovery Reaper     │
        │ • Bounce Circuit Breaker    ││ • Headless Chromium Cap (3) ││ • Expired Lease Handoff     │
        │ • Idempotent Dispatch       ││ • Structured AI Extraction  ││ • Audit Log Retention       │
        └──────────────┬──────────────┘└─────────────────────────────┘└─────────────────────────────┘
                       │
                       ▼
        ┌─────────────────────────────┐
        │     Email Providers         │
        │ • Gmail OAuth (Encrypted)   │
        │ • Custom SMTP / STARTTLS    │
        │ • MockProvider (Test Suite) │
        └─────────────────────────────┘
```

---

## Real VPS Benchmark Results (Ubuntu 24.04 LTS)

Measured under physical execution against Nginx HTTPS terminating to 4 Uvicorn ASGI workers:

| Total Requests | Concurrency | Elapsed Time | Throughput | Latency p50 | Latency p95 | Latency p99 | Errors |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **500** | 100 | 4.89s | **102.3 req/s** | 467.26 ms | 2,456.28 ms | 3,685.94 ms | **0 (0.0%)** |
| **1,000** | 100 | 5.97s | **167.4 req/s** | 231.71 ms | 2,247.43 ms | 3,718.62 ms | **0 (0.0%)** |
| **5,000** | 100 | 15.52s | **322.2 req/s** | 120.83 ms | 1,180.39 ms | 2,452.91 ms | **0 (0.0%)** |
| **10,000** | 100 | 21.84s | **457.9 req/s** | **119.07 ms** | **667.22 ms** | **1,680.19 ms** | **0 (0.0%)** |

*Full benchmark logs available in [`docs/PRODUCTION_LOAD_TEST.md`](docs/PRODUCTION_LOAD_TEST.md).*

---

## Native Linux Production Deployment

For full deployment documentation, see [`docs/PRODUCTION_DEPLOYMENT.md`](docs/PRODUCTION_DEPLOYMENT.md).

### 1. System Prerequisites (Ubuntu 24.04 LTS)
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3.12-dev postgresql postgresql-contrib redis-server nginx git curl libpq-dev
```

### 2. Service User & Database Setup
```bash
# Create dedicated unprivileged service user
sudo useradd -r -s /bin/bash -d /opt/leadflow-ai leadflow

# Configure PostgreSQL
sudo -u postgres psql -c "CREATE USER leadflow WITH PASSWORD 'YOUR_SECURE_PASSWORD' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE leadflow_production OWNER leadflow;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE leadflow_production TO leadflow;"
```

### 3. Deploy Application Code & Virtualenv
```bash
sudo git clone https://github.com/mostlyunstable/leadflow-ai.git /opt/leadflow-ai
sudo chown -R leadflow:leadflow /opt/leadflow-ai

sudo -u leadflow python3.12 -m venv /opt/leadflow-ai/.venv
sudo -u leadflow /opt/leadflow-ai/.venv/bin/pip install -r /opt/leadflow-ai/requirements.txt
```

### 4. Configure Production Environment
```bash
sudo mkdir -p /etc/leadflow
sudo cp /opt/leadflow-ai/.env.example /etc/leadflow/leadflow.env
sudo chmod 600 /etc/leadflow/leadflow.env
sudo chown leadflow:leadflow /etc/leadflow/leadflow.env
sudo ln -sf /etc/leadflow/leadflow.env /opt/leadflow-ai/.env

# Apply Alembic database migrations
sudo -u leadflow /opt/leadflow-ai/.venv/bin/alembic upgrade head
```

### 5. Install Systemd Units & Nginx
```bash
# Install and enable systemd units
sudo cp /opt/leadflow-ai/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now leadflow-api leadflow-campaign-worker leadflow-enrichment-worker leadflow-maintenance-worker

# Install Nginx configuration
sudo cp /opt/leadflow-ai/deploy/nginx/leadflow.conf /etc/nginx/sites-available/leadflow.conf
sudo ln -sf /etc/nginx/sites-available/leadflow.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 6. Verify Production Health
```bash
# Check readiness probe
curl -k https://127.0.0.1/health/ready
# {"status":"ready","app":"LeadFlow AI","version":"2.0.0","checks":{"database":"connected","redis":"connected"}}

# Run full physical validation suite (32 checks)
sudo bash /opt/leadflow-ai/scripts/vps_production_validation.sh https://127.0.0.1
```

---

## Local Development & Automated Testing

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run full automated test suite (79 tests)
pytest tests/ -v

# 4. Start local development server
python main.py
```

---

## Operational Documentation Index

Detailed architectural specs, threat models, and runbooks are available in [`docs/`](docs/):

- **Validation & Benchmarks:**
  - [`docs/REAL_WORLD_PRODUCTION_VALIDATION.md`](docs/REAL_WORLD_PRODUCTION_VALIDATION.md) — 32-point physical validation report on Ubuntu 24.04 LTS.
  - [`docs/PRODUCTION_LOAD_TEST.md`](docs/PRODUCTION_LOAD_TEST.md) — 100-concurrency load test benchmarks through Nginx.
  - [`docs/PRODUCTION_READINESS_MATRIX.md`](docs/PRODUCTION_READINESS_MATRIX.md) — Component-by-component operational readiness matrix.
- **Operations & Runbooks:**
  - [`docs/PRODUCTION_DEPLOYMENT.md`](docs/PRODUCTION_DEPLOYMENT.md) — Complete native Ubuntu 24.04 deployment runbook.
  - [`docs/DISASTER_RECOVERY.md`](docs/DISASTER_RECOVERY.md) — Backup, restore, RTO/RPO, and corruption drills.
  - [`docs/DATABASE_OPERATIONS.md`](docs/DATABASE_OPERATIONS.md) — Migration guides, pool sizing, and failover runbooks.
  - [`docs/REDIS_FAILURE_BEHAVIOR.md`](docs/REDIS_FAILURE_BEHAVIOR.md) — Outage degradation, fallback modes, and recovery behavior.
  - [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — SRE monitoring, rate limit handling, and alerting runbook.
- **Architecture & Design:**
  - [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Technical architecture and domain models.
  - [`docs/HLD.md`](docs/HLD.md) — High-Level Design document.
  - [`docs/LLD.md`](docs/LLD.md) — Low-Level Design document.
  - [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) — Full relational schema, indexes, and constraints.
  - [`docs/EMAIL_IDEMPOTENCY.md`](docs/EMAIL_IDEMPOTENCY.md) — Idempotency guarantees and replay prevention.
  - [`docs/MULTI_PROCESS_AUDIT.md`](docs/MULTI_PROCESS_AUDIT.md) — Multi-process concurrency and state boundaries.
- **Security & Quality:**
  - [`docs/SECURITY.md`](docs/SECURITY.md) — Threat model, SSRF defenses, and cryptographic controls.
  - [`docs/TESTING.md`](docs/TESTING.md) — Test architecture and CI test runbook.
  - [`docs/FINAL_ENGINEERING_REPORT.md`](docs/FINAL_ENGINEERING_REPORT.md) — Forensic audit and rebuild summary.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
