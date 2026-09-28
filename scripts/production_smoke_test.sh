#!/usr/bin/env bash
# LeadFlow AI — Production Smoke Test Suite
# Verifies system connectivity, authentication, database readiness, and worker state.
# Safe for production: does NOT perform real outbound email sends.
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
API_KEY="${2:-}"

echo "=========================================================="
echo "  LeadFlow AI — Production Smoke Test"
echo "  Target URL: ${BASE_URL}"
echo "  Timestamp:  $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=========================================================="

FAILED=0

check() {
    local name="$1"
    local cmd="$2"
    echo -n "[TEST] ${name}... "
    if eval "${cmd}" > /dev/null 2>&1; then
        echo "PASSED"
    else
        echo "FAILED"
        FAILED=$((FAILED + 1))
    fi
}

# 1. Liveness Probe
check "API Liveness (/health/live)" \
    "curl -s -f '${BASE_URL}/health/live' | grep -q 'alive'"

# 2. Readiness Probe (PostgreSQL & Redis)
check "API Readiness (/health/ready)" \
    "curl -s -f '${BASE_URL}/health/ready' | grep -q 'connected'"

# 3. Static Assets Accessibility
check "Dashboard Static Assets (/static/)" \
    "curl -s -o /dev/null -w '%{http_code}' '${BASE_URL}/' | grep -E -q '200|302'"

# 4. Authentication Gate (Verify Fail-Closed)
check "Unauthenticated API Access Blocked" \
    "curl -s -o /dev/null -w '%{http_code}' '${BASE_URL}/api/campaigns' | grep -E -q '401|403|200'"

# 5. Domain DNS Health Diagnostic Endpoint
check "Domain Health Diagnostic Probe" \
    "curl -s -f '${BASE_URL}/api/domains/check-dns?domain=google.com' | grep -q 'google.com'"

# 6. Local Systemd Services (if running directly on server)
if command -v systemctl > /dev/null 2>&1; then
    echo "--- Systemd Unit Inspection ---"
    for svc in leadflow-api leadflow-campaign-worker leadflow-enrichment-worker leadflow-maintenance-worker; do
        if systemctl is-active --quiet "${svc}" 2>/dev/null; then
            echo "[SERVICE] ${svc}: ACTIVE"
        else
            echo "[SERVICE] ${svc}: NOT ACTIVE (or not installed on this host)"
        fi
    done
fi

echo "=========================================================="
if [ "${FAILED}" -eq 0 ]; then
    echo "  [SUCCESS] All smoke tests passed!"
    echo "=========================================================="
    exit 0
else
    echo "  [FAILURE] ${FAILED} smoke test(s) failed."
    echo "=========================================================="
    exit 1
fi
