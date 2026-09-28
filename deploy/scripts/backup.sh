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
find "${BACKUP_DIR}" -type f -name "leadflow_*.dump" -mtime +14 -delete
find "${BACKUP_DIR}" -type f -name "leadflow_*.dump.sha256" -mtime +14 -delete
echo "[INFO] Backup retention purge complete (kept 14 days)."
