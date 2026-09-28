#!/usr/bin/env bash
# LeadFlow AI — Production Zero-Downtime Deployment Script
# Targets native Linux server with systemd, Nginx, PostgreSQL, and Redis.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/leadflow-ai}"
VENV_DIR="${APP_DIR}/.venv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "  LeadFlow AI — Production Deployment Process"
echo "  Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=========================================================="

# 1. Verification of execution context
if [ "$(id -u)" -eq 0 ]; then
    echo "[WARNING] Running as root. Ensure file permissions remain assigned to 'leadflow' user."
fi

if [ ! -d "${APP_DIR}" ]; then
    echo "[ERROR] Application directory ${APP_DIR} does not exist!"
    exit 1
fi

cd "${APP_DIR}"

# 2. Automated Safety Backup prior to migration
echo "[STEP 1/7] Creating pre-deployment database backup..."
if [ -x "${SCRIPT_DIR}/backup.sh" ]; then
    "${SCRIPT_DIR}/backup.sh" || echo "[WARNING] Backup script reported non-zero exit; proceed with caution."
else
    echo "[INFO] No executable backup.sh found; skipping pre-deployment backup."
fi

# 3. Update Python Virtual Environment Dependencies
echo "[STEP 2/7] Installing / verifying Python dependencies..."
source "${VENV_DIR}/bin/activate"
pip install -r requirements.txt --quiet --no-cache-dir

# 4. Run Alembic Database Migrations
echo "[STEP 3/7] Applying database migrations..."
alembic upgrade head

# 5. Gracefully Drain and Restart Background Workers
# Using SIGTERM allows workers to complete currently in-flight sends before terminating
echo "[STEP 4/7] Gracefully stopping and restarting background workers..."
systemctl stop --signal=SIGTERM leadflow-campaign-worker.service || true
systemctl stop --signal=SIGTERM leadflow-enrichment-worker.service || true
systemctl stop --signal=SIGTERM leadflow-maintenance-worker.service || true

# 6. Reload Systemd Services and Start Components
echo "[STEP 5/7] Starting updated systemd units..."
systemctl daemon-reload
systemctl restart leadflow-api.service
systemctl restart leadflow-campaign-worker.service
systemctl restart leadflow-enrichment-worker.service
systemctl restart leadflow-maintenance-worker.service

# 7. Reload Nginx Web Server
echo "[STEP 6/7] Validating and reloading Nginx..."
nginx -t
systemctl reload nginx

# 8. Post-Deployment Health Check Verification
echo "[STEP 7/7] Verifying API readiness probe..."
sleep 2

HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health/ready || echo "000")

if [ "${HEALTH_RESPONSE}" -eq 200 ]; then
    echo "=========================================================="
    echo "  [SUCCESS] Deployment successfully completed!"
    echo "  API Status: READY (HTTP 200)"
    echo "=========================================================="
    exit 0
else
    echo "=========================================================="
    echo "  [ERROR] Health probe failed with HTTP ${HEALTH_RESPONSE}!"
    echo "  Check logs: journalctl -u leadflow-api -n 50 --no-pager"
    echo "=========================================================="
    exit 1
fi
