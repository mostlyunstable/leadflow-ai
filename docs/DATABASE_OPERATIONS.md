# LeadFlow AI — Production Database Operations & Runbook

**Version:** 2.0.0-PROD  
**Target:** PostgreSQL 16 (Native Linux)  
**Standard Backup Directory:** `/var/backups/leadflow`  

---

## 1. Backup Procedures

### 1.1 Automated Daily Full Logical Backup (`pg_dump`)
LeadFlow AI requires automated nightly backups using `pg_dump` with custom directory format (`-Fd`) or compressed tar/custom format (`-Fc`), producing transactional point-in-time consistent archives.

Run via `/usr/local/bin/leadflow-backup.sh` (or `deploy/scripts/backup.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/leadflow"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/leadflow_${TIMESTAMP}.dump"
DB_NAME="leadflow_production"
DB_USER="leadflow"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

echo "[INFO] Starting database backup for ${DB_NAME} at $(date)..."
pg_dump -h 127.0.0.1 -U "${DB_USER}" -d "${DB_NAME}" -F c -b -v -f "${BACKUP_FILE}"

# Generate SHA256 checksum for verification
sha256sum "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"
echo "[SUCCESS] Backup complete: ${BACKUP_FILE} (Checksum: $(cat "${BACKUP_FILE}.sha256"))"

# Retain backups for 14 days
find "${BACKUP_DIR}" -type f -name "leadflow_*.dump" -mtime +14 -delete
find "${BACKUP_DIR}" -type f -name "leadflow_*.dump.sha256" -mtime +14 -delete
```

---

## 2. Restore Procedures (Verified Runbook)

> **Important**: A backup that has never been tested in a restoration drill is unverified. Always test restore procedures in staging before touching production.

### 2.1 Restoration Steps from `.dump` Archive
```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="$1"
TARGET_DB="leadflow_restored"
DB_USER="leadflow"

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
    echo "[ERROR] Usage: $0 /path/to/leadflow_YYYYMMDD_HHMMSS.dump"
    exit 1
fi

# 1. Verify Checksum
if [ -f "${BACKUP_FILE}.sha256" ]; then
    echo "[INFO] Verifying backup checksum..."
    sha256sum -c "${BACKUP_FILE}.sha256"
fi

# 2. Terminate existing connections to target database
echo "[INFO] Terminating active connections to ${TARGET_DB}..."
psql -h 127.0.0.1 -U "${DB_USER}" -d postgres -c "
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = '${TARGET_DB}'
  AND pid <> pg_backend_pid();" || true

# 3. Drop & Recreate clean target database
echo "[INFO] Recreating clean database ${TARGET_DB}..."
psql -h 127.0.0.1 -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${TARGET_DB};"
psql -h 127.0.0.1 -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${TARGET_DB} OWNER ${DB_USER};"

# 4. Restore using pg_restore
echo "[INFO] Restoring data from ${BACKUP_FILE}..."
pg_restore -h 127.0.0.1 -U "${DB_USER}" -d "${TARGET_DB}" -v "${BACKUP_FILE}"

# 5. Run integrity verification query
echo "[INFO] Running data sanity checks..."
psql -h 127.0.0.1 -U "${DB_USER}" -d "${TARGET_DB}" -c "
SELECT 
    (SELECT count(*) FROM organizations) AS organizations_count,
    (SELECT count(*) FROM leads) AS leads_count,
    (SELECT count(*) FROM campaigns) AS campaigns_count,
    (SELECT count(*) FROM send_jobs) AS send_jobs_count;"

echo "[SUCCESS] Database restoration and verification complete."
```

---

## 3. Migration Strategy (Alembic)

### 3.1 Applying Migrations
All schema updates MUST be managed through Alembic revisions. Never apply manual DDL changes directly to production tables.
```bash
# Run pending migrations
cd /opt/leadflow-ai
source .venv/bin/activate
alembic upgrade head
```

### 3.2 Rollback Strategy
If an applied migration causes application errors:
```bash
# Revert the most recent migration
alembic downgrade -1

# Or revert to a specific stable revision hash
alembic downgrade <revision_id>
```
*Note: Schema migrations must be backward-compatible (expand/contract pattern) so that rolling back does not corrupt data already written.*

---

## 4. Connection Failures & Pool Tuning

### 4.1 Connection Pool Settings (`database/database.py`)
```python
engine = create_engine(
    DATABASE_URL,
    pool_size=15,             # Persistent active connection pool
    max_overflow=25,          # Burst capacity during high worker concurrency
    pool_timeout=30,          # Seconds to wait before raising TimeoutError
    pool_recycle=1800,        # Recycle connections every 30 minutes
    pool_pre_ping=True,       # Liveness check (SELECT 1) on checkout
)
```
- `pool_pre_ping=True`: Detects closed connections (e.g. PostgreSQL restart, firewall timeout) and automatically recovers healthy sockets without throwing 500 errors to users.

### 4.2 Handling PostgreSQL Outages
When PostgreSQL goes down:
1. API endpoints return `503 Service Unavailable` via the `/health/ready` check.
2. Background workers catch `OperationalError`, log an alert, and sleep exponentially (5s $\to$ 10s $\to$ 20s $\to$ 60s) before re-attempting connection.
3. No job state is lost: in-flight jobs retain their status in PostgreSQL WAL once the database recovers.

---

## 5. Corruption Response & Recovery Playbook

If a PostgreSQL table suffers physical corruption (e.g., bad disk block, power loss during unbuffered write):

1. **Isolate Services**:
   ```bash
   sudo systemctl stop leadflow-api leadflow-campaign-worker leadflow-enrichment-worker leadflow-maintenance-worker
   ```
2. **Inspect PostgreSQL Server Logs**:
   ```bash
   sudo journalctl -u postgresql -e --no-pager
   ```
3. **Run pg_waldump / zero_damaged_pages (Emergency)**:
   If single page corruption prevents startup, set `zero_damaged_pages = on` in `postgresql.conf` to bypass the corrupted block, dump the table, and reconstruct data from audit logs.
4. **Restore from Clean Nightly Backup**:
   Execute the verified restore procedure (`deploy/scripts/restore.sh`) to the latest known good `.dump` file.
5. **Replay In-Flight Transactions via Audit Logs**:
   Use `audit_logs` entries recorded after the backup timestamp to reconcile missing campaign dispatches and recipient statuses.
