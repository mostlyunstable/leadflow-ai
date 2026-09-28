# LeadFlow AI — Redis Failure & Graceful Degradation Behavior

**Document Version:** 2.0.0-PROD  
**Domain:** Distributed Resilience & Infrastructure Outage Playbook  
**Classification:** Tested Operational Behavior  

---

## 1. Architectural Role of Redis in LeadFlow AI

In LeadFlow AI, **PostgreSQL is the sole authoritative source of truth** for all business-critical entities:
- Campaigns & Leads
- Email Records & SendJobs
- Provider Accounts & Credentials
- Suppression Lists & Audit Logs

**Redis is strictly coordination and acceleration infrastructure**. It is never treated as permanent storage.

---

## 2. Component Behavior During Redis Outages

| Component | Behavior When Redis is DOWN | Behavior When Redis RECOVERS | Data Loss Risk |
| :--- | :--- | :--- | :--- |
| **API Server (`leadflow-api`)** | Continues serving all REST endpoints. `/health/ready` reports `checks.redis = "degraded: connection refused"`, but HTTP status remains 200 OK because database connectivity is verified. | Reconnects on next request; `/health/ready` automatically reports `checks.redis = "connected"`. | **Zero**. All requests persist to PostgreSQL. |
| **Durable Queue (`core/queue.py`)** | Continues without interruption. Job claims use PostgreSQL row locking (`SELECT ... FOR UPDATE SKIP LOCKED`). | Unchanged. | **Zero**. State machine lives in SQL. |
| **Campaign Worker (`workers/campaign_worker.py`)** | Dispatches continue. Rate limiting falls back to transactional row locks on `email_provider_accounts.sends_today` and `sends_this_hour`. Pacing delay defaults to database timestamps. | Reconnects to Redis token bucket for high-speed rate-limiting. | **Zero**. Counters are audited in SQL. |
| **Enrichment Worker (`workers/enrichment_worker.py`)** | Drains `enrichment_jobs` via PostgreSQL row leases. Unaffected by Redis status. | Unaffected. | **Zero**. |
| **Maintenance Worker (`workers/maintenance_worker.py`)** | Scans PostgreSQL for expired leases (`lease_expires_at < now`). Unaffected by Redis status. | Unaffected. | **Zero**. |

---

## 3. Simulated Outage Test Verification

### Outage Simulation Steps:
```text
1. API & Workers active with simulated campaign.
2. Invalidate REDIS_URL or stop Redis daemon:
   sudo systemctl stop redis-server
3. Probe /health/ready endpoint:
   curl -s http://127.0.0.1:8000/health/ready
   Response: {"status": "ready", "checks": {"database": "connected", "redis": "degraded: Connection refused"}}
4. Dispatch campaign SendJobs:
   Worker claims SendJob, verifies policy in PostgreSQL, dispatches via MockEmailProvider, commits status='sent'.
   Job completes successfully.
5. Restart Redis:
   sudo systemctl start redis-server
   curl -s http://127.0.0.1:8000/health/ready
   Response: {"status": "ready", "checks": {"database": "connected", "redis": "connected"}}
6. Result: PASS — System operates safely in degraded mode with zero data loss.
```
