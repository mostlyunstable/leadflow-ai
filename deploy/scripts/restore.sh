#!/usr/bin/env bash
# LeadFlow AI — Production PostgreSQL Database Restore
# Restores a verified .dump backup archive into a target database.
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 /path/to/leadflow_YYYYMMDD_HHMMSS.dump [target_database]"
    exit 1
fi

BACKUP_FILE="$1"
TARGET_DB="${2:-leadflow_production}"
DB_USER="${DB_USER:-leadflow}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

# Extract credentials from /etc/leadflow/leadflow.env if present
if [ -z "${PGPASSWORD:-}" ] && [ -f /etc/leadflow/leadflow.env ]; then
    DB_URL=$(grep "^DATABASE_URL=" /etc/leadflow/leadflow.env | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [[ "${DB_URL}" =~ postgresql://([^:]+):([^@]+)@([^:/]+):?([0-9]*)/(.*) ]]; then
        export PGPASSWORD="${BASH_REMATCH[2]}"
        DB_USER="${DB_USER:-${BASH_REMATCH[1]}}"
        DB_HOST="${DB_HOST:-${BASH_REMATCH[3]}}"
        DB_PORT="${DB_PORT:-${BASH_REMATCH[4]:-5432}}"
    fi
fi

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "[ERROR] Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# 1. Verify Checksum if available
if [ -f "${BACKUP_FILE}.sha256" ]; then
    echo "[INFO] Verifying checksum against ${BACKUP_FILE}.sha256..."
    sha256sum -c "${BACKUP_FILE}.sha256"
    echo "[SUCCESS] Checksum verified."
fi

echo "[WARNING] You are about to restore into '${TARGET_DB}' on ${DB_HOST}:${DB_PORT}."
echo "[INFO] Terminating active connections to '${TARGET_DB}'..."

psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = '${TARGET_DB}'
  AND pid <> pg_backend_pid();" || true

# Recreate target database
echo "[INFO] Recreating clean database '${TARGET_DB}'..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${TARGET_DB};"
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${TARGET_DB} OWNER ${DB_USER};"

# Restore using pg_restore
echo "[INFO] Restoring database archive..."
pg_restore -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${TARGET_DB}" -v "${BACKUP_FILE}"

# Run sanity verification
echo "[INFO] Verifying table counts in restored database..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${TARGET_DB}" -c "
SELECT 
    (SELECT count(*) FROM organizations) AS organizations,
    (SELECT count(*) FROM leads) AS leads,
    (SELECT count(*) FROM campaigns) AS campaigns,
    (SELECT count(*) FROM send_jobs) AS send_jobs;"

echo "[SUCCESS] Database restoration and verification successfully completed."
