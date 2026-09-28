# LeadFlow AI — Automated Testing Suite

---

## 1. Test Architecture

The testing framework uses `pytest` with in-memory database isolation and mock providers for lightning-fast, reproducible execution without external network dependencies.

```text
tests/
├── conftest.py                # Fixtures, test DB, multi-tenant test organizations
├── unit/
│   ├── test_security.py       # Password hashing, Fernet encryption, JWT, SSRF checks
│   ├── test_queue.py          # Enqueueing, leases, exponential backoff, crash recovery
│   ├── test_sending_policy.py # Hourly/daily limits, suppression list, circuit breakers
│   ├── test_llm_provider.py   # Pydantic schemas, Mock LLM, prompt sanitization
│   └── test_reply_classifier.py# Rule-based heuristics and classification precedence
├── integration/
│   ├── test_enrichment_pipeline.py # Layered HTML parsing and SSRF blocks
│   └── test_database_constraints.py # Scoped unique constraints, cascades, rollbacks
├── api/
│   ├── test_auth_and_multitenancy.py # Login and tenant isolation
│   └── test_campaigns_api.py  # Campaign lifecycle, CSV upload, domain diagnostics
├── contract/
│   └── test_provider_contract.py # EmailProvider protocol and failure modes
├── e2e/
│   └── test_campaign_execution_flow.py # End-to-end full campaign delivery lifecycle
└── failure/
    └── test_resilience_and_failures.py # Crash recovery, network timeouts, fail-closed
```

---

## 2. Running Tests

Run the complete test suite:
```bash
pytest tests/ -v
```

Run with coverage report:
```bash
pytest tests/ --cov=. --cov-report=term-missing
```

Run specific test categories:
```bash
# Security & SSRF tests
pytest tests/unit/test_security.py -v

# Multi-tenant isolation tests
pytest tests/api/test_auth_and_multitenancy.py -v

# End-to-end campaign execution
pytest tests/e2e/test_campaign_execution_flow.py -v

# Crash and failure resilience
pytest tests/failure/test_resilience_and_failures.py -v
```
