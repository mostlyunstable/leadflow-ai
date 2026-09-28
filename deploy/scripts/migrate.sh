#!/usr/bin/env bash
# LeadFlow AI — Database Migration Runner
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/leadflow-ai}"
VENV_DIR="${APP_DIR}/.venv"

echo "[INFO] Running database migrations in ${APP_DIR}..."

if [ ! -d "${VENV_DIR}" ]; then
    echo "[ERROR] Virtualenv not found at ${VENV_DIR}"
    exit 1
fi

source "${VENV_DIR}/bin/activate"
cd "${APP_DIR}"

# Run Alembic upgrade
alembic upgrade head

echo "[SUCCESS] Database schema is up to date with HEAD."
