# LeadFlow AI — Operational & SRE Runbook

---

## 1. Monitoring & Health Probes

### HTTP Health Check
- **Endpoint:** `GET /health`
- **Expected Status:** `200 OK`
- **Response:**
  ```json
  {
    "status": "healthy",
    "app": "LeadFlow AI",
    "version": "2.0.0",
    "environment": "production"
  }
  ```

### Key Metrics to Monitor
1. **Queue Depth:** Number of jobs in `QUEUED` state.
2. **Lease Age:** Alert if any `SendJob` has `status == 'processing'` and `lease_expires_at < NOW() - 5 minutes`.
3. **Bounce Rate:** Alert if campaign bounce rate exceeds `MAX_BOUNCE_RATE_PERCENT` (5%).
4. **Worker Throughput:** Jobs processed per worker per minute.

---

## 2. Common Operational Tasks

### Restarting Workers
Workers can be restarted at any time without data loss:
```bash
docker compose restart campaign-worker
```
Any job currently being processed by a restarted worker will experience lease expiration and be automatically recovered by sibling workers or the restarted worker.

### Recovering from Provider 429 Rate Limits
If an email provider returns rate limit errors (HTTP 429):
1. The `DurableQueue` marks the job as `RETRY_WAIT`.
2. Computes exponential backoff delay (`backoff_base * 2^(attempt-1)`).
3. Reschedules the job for future execution automatically.
4. If rate limits persist, reduce `HOURLY_SEND_LIMIT` and `DAILY_SEND_LIMIT` in `.env`.

### Inspecting Domain Health
Run the deliverability diagnostic for any sending domain:
```bash
curl -X GET "http://localhost:8000/api/domains/check?domain=yourdomain.com" \
  -H "X-API-Key: your_dashboard_api_key"
```
Ensure SPF and DMARC records are marked as present before activating high-volume campaigns.
