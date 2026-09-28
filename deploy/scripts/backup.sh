#!/usr/bin/env bash
# LeadFlow AI — Production PostgreSQL Database Backup
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/leadflow}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/leadflow_${TIMESTAMP}.dump"
DB_NAME="${DB_NAME:-leadflow_production}"
DB_USER="${DB_USER:-leadflow}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

# Extract credentials from /etc/leadflow/leadflow.env if present
if [ -z "${PGPASSWORD:-}" ] && [ -f /etc/leadflow/leadflow.env ]; then
    DB_URL=$(grep "^DATABASE_URL=" /etc/leadflow/leadflow.env | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [[ "${DB_URL}" =~ postgresql://([^:]+):([^@]+)@([^:/]+):?([0-9]*)/(.*) ]]; then
        export PGPASSWORD="${BASH_REMATCH[2]}"
        DB_USER="${BASH_REMATCH[1]}"
        DB_HOST="${BASH_REMATCH[3]}"
        DB_PORT="${BASH_REMATCH[4]:-5432}"
        DB_NAME="${BASH_REMATCH[5]}"
    fi
fi

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

echo "[INFO] Starting database backup for ${DB_NAME} at $(date)..."

# Perform pg_dump in custom compressed format
pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -F c -b -v -f "${BACKUP_FILE}"

# Generate SHA256 checksum
sha256sum "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"

echo "[SUCCESS] Backup created successfully: ${BACKUP_FILE}"
echo "[INFO] Checksum: $(cat "${BACKUP_FILE}.sha256")"

# Retain only the last 14 days of backups
cd "${BACKUP_DIR}"
find . -maxdepth 1 -type f -name "leadflow_*.dump" -mtime +14 -delete
find . -maxdepth 1 -type f -name "leadflow_*.dump.sha256" -mtime +14 -delete
echo "[INFO] Backup retention purge complete (kept 14 days)."
