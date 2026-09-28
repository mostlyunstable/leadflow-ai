# LeadFlow AI — Multi-Process & Shared-State Concurrency Audit

**Audit Date:** 2026-09-28  
**Auditor:** Principal Systems Architect & SRE  
**Scope:** Verification of process-local state, concurrency hazards, multi-worker consistency across Uvicorn process workers (Workers 1–4) and background daemons.

---

## 1. Exhaustive Codebase State Audit

Every directory (`api/`, `core/`, `database/`, `modules/`, `services/`, `workers/`, `main.py`) was scanned for process-local state, threading locks, in-memory queues, and uncoordinated caches.

### 1.1 State Classification Inventory

| Subsystem / File | Pattern Discovered | Nature of State | Multi-Process Impact (Workers 1–4) | Risk Assessment | Mitigation / Verification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`core/queue.py`** | `session.query(SendJob)` | PostgreSQL DB State | **None**. Rows are locked atomically via `FOR UPDATE SKIP LOCKED`. Any API or worker process sees identical state. | **SECURE** | DB is sole source of truth. |
| **`api/routes.py`** | `AuthContext` | Per-request local object | **None**. Instantiated per HTTP request from decoded stateless JWT or DB query. | **SECURE** | Fully stateless. |
| **`api/routes.py`** | `tempfile.NamedTemporaryFile` | Ephemeral disk file during CSV upload | **None**. CSV file is read into memory, parsed immediately into DB `Lead` entities, and temporary file is closed and unlinked in a `finally` block. | **SECURE** | No cross-request disk dependence. |
| **`modules/ai_engine/generator.py`** | `SYSTEM_PROMPT` | Constant string | **None**. Immutable module-level string constant. | **SECURE** | Read-only. |
| **`modules/ai_engine/llm_provider.py`** | `_provider_cache` | Module-level cached provider instance | **Safe**. The provider instance (`OpenAILLMProvider` or `MockLLMProvider`) is stateless; credentials are read from environment. | **LOW** | Stateless instance reuse. |
| **`modules/lead_enrichment/pipeline.py`** | `asyncio.Semaphore(3)` | Process-local async semaphore | **Safe**. Caps concurrent Playwright browser pages within each process to prevent local host RAM exhaustion. | **CONTROLLED** | Prevents single-process OOM. |
| **`modules/email_sender/account_manager.py`** | `_clients = {}`, `threading.Lock()` | Legacy process-local dict | **ZERO IMPACT**. Orphaned legacy code; **NOT** imported or called by `api/routes.py` or `workers/campaign_worker.py`. | **ISOLATED** | Dead code isolated. |
| **`modules/email_sender/batch_sender.py`** | `time.sleep()`, `_stop_requested` | Legacy in-process sender | **ZERO IMPACT**. Orphaned legacy code; **NOT** called in production. API routes enqueue into PostgreSQL `send_jobs`. | **ISOLATED** | Dead code isolated. |
| **`services/sending_policy.py`** | Policy checks against DB | PostgreSQL row checks | **None**. Hourly/daily counts and suppression are evaluated against live database rows (`email_provider_accounts` and `suppression_entries`). | **SECURE** | Consistent across all processes. |

---

## 2. Multi-Worker Behavioral Verification (Workers 1–4)

### 2.1 Scenario: User request distributed randomly across Uvicorn workers 1, 2, 3, 4
Because Uvicorn with `--workers 4` spawns 4 OS-level child processes:

```text
Incoming Request -> Nginx (Round-Robin/Least-Conn) -> Uvicorn Master -> Worker N (1..4)
```

1. **Authentication**:
   - Worker 1 signs a JWT upon login (`POST /api/auth/login`).
   - Subsequent request is routed to Worker 3.
   - Worker 3 decodes the JWT using the shared `SECRET_KEY` and decrypts claims (`sub`, `org`, `exp`). Verification succeeds identically without session sticky routing.
2. **Campaign Lifecycle**:
   - Worker 2 receives `POST /api/campaigns/1/start`.
   - Worker 2 writes `SendJob` rows directly to PostgreSQL and sets `Campaign.status = ACTIVE`.
   - Worker 4 receives `GET /api/campaigns/1`. Worker 4 queries PostgreSQL and immediately returns the active state and exact job counts.
3. **Lead Ingestion & Deduplication**:
   - Worker 1 receives CSV upload for `john@company.com`.
   - Worker 3 concurrently receives CSV upload with `john@company.com`.
   - Database constraint `uq_org_lead_email` on `(organization_id, email)` guarantees atomic deduplication at the storage layer; one worker inserts, the other skips or fails closed.
4. **Rate Limiting**:
   - If Redis is active, rate limit counters increment atomically across all workers via Redis `INCR`.
   - If Redis is degraded, rate limit counters are evaluated directly against `email_provider_accounts.sends_today` in PostgreSQL with row locking.

---

## 3. Findings & Verdict

- **No critical in-memory singletons or state stores exist in active production routes.**
- **FastAPI request processing is 100% stateless.**
- **All business entities, counters, and durable queues reside in PostgreSQL.**
- **The system behaves identically regardless of which Uvicorn worker process receives the request.**
