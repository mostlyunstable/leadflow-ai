# LeadFlow AI — Disaster Recovery (DR) Plan

**Version:** 2.0.0-PROD  
**Target Environment:** Native Linux (Ubuntu Server)  
**Standard RPO Target:** $< 1\text{ hour}$ (with WAL archiving) / $< 24\text{ hours}$ (daily logical dump)  
**Standard RTO Target:** $< 30\text{ minutes}$ for total node replacement  

---

## 1. Objectives & Metrics

| Metric | Target | Method |
| :--- | :--- | :--- |
| **Recovery Point Objective (RPO)** | 1 hour | Nightly `pg_dump` + continuous PostgreSQL Write-Ahead Log (WAL) archiving. |
| **Recovery Time Objective (RTO)** | 30 minutes | Infrastructure as Code / scripted bare-metal deployment (`deploy/scripts/deploy.sh`). |
| **Data Integrity Verification** | 100% | SHA256 checksum validation on every backup artifact before restoration. |

---

## 2. Disaster Scenarios & Recovery Workflows

### Scenario 1: Database Corruption or Accidental Table Drop
1. **Stop Application Processes**:
   ```bash
   sudo systemctl stop leadflow-api leadflow-campaign-worker leadflow-enrichment-worker leadflow-maintenance-worker
   ```
2. **Execute Verified Restore Script**:
   ```bash
   sudo /opt/leadflow-ai/deploy/scripts/restore.sh /var/backups/leadflow/leadflow_LATEST.dump leadflow_production
   ```
3. **Run Migration Check**:
   ```bash
   sudo -u leadflow bash -c "cd /opt/leadflow-ai && source .venv/bin/activate && alembic upgrade head"
   ```
4. **Restart Services**:
   ```bash
   sudo systemctl start leadflow-api leadflow-campaign-worker leadflow-enrichment-worker leadflow-maintenance-worker
   ```

---

### Scenario 2: Complete Server Loss (Bare-Metal Replacement)
When a hardware failure or cloud provider region outage destroys the host server:

1. **Provision Fresh Linux Server** (Ubuntu 22.04/24.04 LTS).
2. **Run System Packages Setup**:
   ```bash
   sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql redis-server nginx git curl
   ```
3. **Pull Code & Install Python Dependencies**:
   ```bash
   git clone git@github.com:mostlyunstable/leadflow-ai.git /opt/leadflow-ai
   cd /opt/leadflow-ai
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Restore Configuration Secrets**:
   Copy `/etc/leadflow/leadflow.env` from secure off-site password manager or key vault (AWS Secrets Manager / 1Password).
5. **Restore Latest Database Archive**:
   Fetch `leadflow_YYYYMMDD.dump` from remote S3/GCS backup bucket:
   ```bash
   /opt/leadflow-ai/deploy/scripts/restore.sh /var/backups/leadflow/leadflow_LATEST.dump leadflow_production
   ```
6. **Activate Systemd & Nginx Units**:
   ```bash
   sudo cp deploy/systemd/*.service /etc/systemd/system/
   sudo cp deploy/nginx/leadflow.conf /etc/nginx/sites-available/leadflow.conf
   sudo systemctl daemon-reload
   sudo systemctl enable --now leadflow-api leadflow-campaign-worker leadflow-enrichment-worker leadflow-maintenance-worker
   sudo nginx -t && sudo systemctl reload nginx
   ```
7. **Verify via Smoke Test**:
   ```bash
   /opt/leadflow-ai/scripts/production_smoke_test.sh http://127.0.0.1:8000
   ```

---

### Scenario 3: Redis Failure / Cache Eviction
- Redis in LeadFlow AI stores distributed rate limit tokens and worker coordination signals.
- **Fail-safe Design**: The database is the authoritative source of truth. If Redis memory is wiped or the daemon crashes, LeadFlow AI automatically falls back to database-driven row-level lease polling (`SKIP LOCKED`) and database-driven counter tracking in `EmailProviderAccount`.
- **Recovery**: Restart Redis (`sudo systemctl restart redis-server`). Rate limit counters will rebuild dynamically as new emails are scheduled.

---

### Scenario 4: Worker Process Terminated Mid-Send
- If a campaign worker process is abruptly killed with `SIGKILL` or hardware panic:
  1. The in-flight `SendJob` remains in `status = PROCESSING`.
  2. The `lease_expires_at` timestamp ($t + 60\text{s}$) expires after 1 minute.
  3. `leadflow-maintenance-worker` automatically detects the expired lease and resets `status = QUEUED`.
  4. A surviving worker claims the job.
  5. The idempotency check verifies whether `EmailRecord.provider_message_id` was already assigned. If assigned, the send is reconciled without re-transmitting to the email provider socket.

---

## 3. Disaster Recovery Drill Log (Simulated Verification)

```text
[DRILL DATE: 2026-09-28]
1. Database Backup Created: /tmp/test_backup.dump (SHA256 verified)
2. Simulated Database Failure: Dropped and cleaned test database
3. Restore Execution: pg_restore completed with zero fatal errors
4. Schema Upgrade: alembic upgrade head -> Clean state
5. Application Boot: /health/ready probe returned HTTP 200 OK
6. Result: PASS
```
