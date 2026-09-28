# LeadFlow AI — Production Deployment Guide

---

## 1. Prerequisites
- Docker Engine 24+ and Docker Compose v2+
- A registered domain with access to configure DNS (SPF, DKIM, DMARC, MX)
- PostgreSQL 15+ and Redis 7+ (provided in Compose or managed via AWS RDS / ElastiCache)

---

## 2. Environment Configuration

Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```

Set the following required production variables:

```bash
# ── Application Environment ──────────────────────────────────────────
ENVIRONMENT=production
DEBUG=false
HOST=0.0.0.0
PORT=8000

# ── Cryptography & Security (MANDATORY IN PRODUCTION) ────────────────
# Generate with: openssl rand -hex 32
SECRET_KEY=9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e

# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=YourCustomFernetBase64KeyHere32BytesLong=

# Automation API Key
DASHBOARD_API_KEY=leadflow_api_live_your_random_token_here

# ── Database & Redis ─────────────────────────────────────────────────
DATABASE_URL=postgresql://leadflow_user:your_strong_db_password@postgres:5432/leadflow_db
REDIS_URL=redis://redis:6379/0

# ── AI Provider ──────────────────────────────────────────────────────
OPENAI_API_KEY=nvapi-your-nvidia-nim-or-openai-key
OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1
OPENAI_MODEL=meta/llama-3.1-70b-instruct
```

---

## 3. Docker Compose Deployment

Run the complete multi-container stack:
```bash
docker compose up -d --build
```

Verify all services are healthy:
```bash
docker compose ps
```

Check logs:
```bash
docker compose logs -f web
docker compose logs -f campaign-worker
```

---

## 4. Database Migrations

Alembic migrations run automatically on container startup. To execute migrations manually:
```bash
docker compose exec web alembic upgrade head
```

To rollback a migration:
```bash
docker compose exec web alembic downgrade -1
```

---

## 5. Scaling Workers

To handle higher outbound volumes, scale the campaign worker container horizontally:
```bash
docker compose up -d --scale campaign-worker=3
```
Because the durable queue uses atomic database lease locks and worker ownership, multiple workers safely consume jobs concurrently without race conditions or duplicate sends.
