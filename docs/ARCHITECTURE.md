# LeadFlow AI — Production System Architecture
**Version:** 2.0.0  
**Status:** Production Standard  

---

## 1. System Overview

LeadFlow AI is an enterprise-grade outbound intelligence and multi-tenant campaign delivery platform. It automates lead ingestion, SSRF-defended website enrichment, LLM personalization, sending policy compliance, and durable email dispatch.

```
                          ┌────────────────────────────────┐
                          │   Frontend SPA (Vanilla JS)    │
                          └───────────────┬────────────────┘
                                          │ HTTPS / JWT / API-Key
                                          ▼
                          ┌────────────────────────────────┐
                          │   FastAPI Gateway / REST API   │
                          ├────────────────────────────────┤
                          │ • Security Headers Middleware  │
                          │ • Fail-Closed Auth Dependency  │
                          │ • Multi-Tenant Scope Resolver  │
                          │ • Idempotency Enforcer         │
                          └──────┬──────────────────┬──────┘
                                 │                  │
               Enqueue SendJobs  │                  │ Relational Queries
                                 ▼                  ▼
┌──────────────────────────────────────┐     ┌───────────────────────────────────┐
│ Redis / Durable Job Queue            │     │ PostgreSQL (Multi-Tenant Schema)  │
├──────────────────────────────────────┤     ├───────────────────────────────────┤
│ • Worker Leases (60s lock)           │     │ • Organizations / Users / Members │
│ • Atomic Claims                      │     │ • Leads / Companies / Campaigns   │
│ • Crash Recovery Reaper              │     │ • EmailRecords / SendJobs         │
└──────────────────┬───────────────────┘     │ • SendAttempts / AuditLogs        │
                   │                         │ • Encrypted Credentials (Fernet)  │
                   │ Claim                   └─────────────────▲─────────────────┘
                   ▼                                           │
┌──────────────────────────────────────┐                       │
│ Standalone Campaign Workers          │                       │
├──────────────────────────────────────┤                       │
│ • Sending Policy Engine              ├───────────────────────┘
│ • Hourly/Daily Cap Evaluator         │
│ • Bounce Rate Circuit Breaker        │
│ • Idempotency Pre-Check              │
└──────┬───────────────────────┬───────┘
       │                       │
       ▼                       ▼
┌─────────────────────┐ ┌─────────────────────┐
│ EmailProvider       │ │ Enrichment Engine   │
├─────────────────────┤ ├─────────────────────┤
│ • GmailProvider     │ │ • SSRFSafeHTTPFetch │
│ • SMTPProvider      │ │ • BrowserFallback   │
│ • MockEmailProvider │ │ • Confidence Scorer │
└─────────────────────┘ └─────────────────────┘
```

---

## 2. Core Architectural Pillars

### 2.1 Multi-Tenancy & Data Isolation
- **Tenant Entity:** `Organization` acts as the root boundary for all tenant data.
- **Scoping Rule:** Every table containing business data (`leads`, `campaigns`, `email_records`, `send_jobs`, `email_provider_accounts`, `domains`, `audit_logs`) has a mandatory `organization_id` foreign key.
- **Composite Unique Constraints:** Leads are scoped to unique `(organization_id, email)` tuples, allowing different tenants to reach out to the same contact without conflict.
- **Service Layer Enforcement:** The `AuthContext` dependency extracts the tenant organization from verified JWT claims or API keys and injects it into all queries and mutations.

### 2.2 Durable Job Queue & State Machine
Execution is decoupled from web processes:
- Campaign start triggers **batch job enqueueing**, creating persistent `SendJob` records.
- Workers atomically claim jobs with a **lease lock** (`lease_worker_id`, `lease_expires_at`).
- If a worker crashes or is killed mid-send, the lease expires. Sibling workers automatically reap or claim the orphaned job.
- State transitions:
  ```
  PENDING ──► QUEUED ──► PROCESSING ──► SENT
                             │
                             ├────────► RETRY_WAIT (Exponential Backoff)
                             │
                             └────────► FAILED (Dead Letter after Max Retries)
  ```

### 2.3 Idempotency Guarantees
- Every outbound email receives a deterministic `idempotency_key` based on `(organization_id, campaign_id, lead_id, email_record_id)`.
- If a provider accepts an email but a network timeout prevents the client from receiving the 200 response, retrying the job will inspect `EmailRecord.provider_message_id`. If already present, the worker marks the job complete without resending.

### 2.4 Security & Cryptography at Rest
- **Credential Encryption:** All OAuth tokens, refresh tokens, and SMTP secrets are encrypted using authenticated symmetric encryption (`Fernet` / AES-128-CBC + HMAC-SHA256) using a 32-byte key (`ENCRYPTION_KEY`). Plaintext tokens are never stored on disk.
- **Password Hashing:** Passwords use PBKDF2-HMAC-SHA256 with 310,000 iterations and random 16-byte salts.
- **Fail-Closed Configuration:** Missing or default secret keys in production halt application startup.

### 2.5 SSRF-Defended Layered Enrichment
- Target URLs are validated before network requests.
- Hostnames are resolved to IP addresses and verified against private subnets (RFC 1918), loopbacks, link-local metadata (`169.254.169.254`), and reserved addresses.
- Redirects are intercepted and re-validated at every hop.
- When dynamic single-page apps or Cloudflare challenges are detected, the system safely falls back to a headless browser worker.
