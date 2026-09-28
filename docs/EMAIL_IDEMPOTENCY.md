# LeadFlow AI — Email Delivery Idempotency & Failure Reconciliation

**Document Version:** 2.0.0-PROD  
**Domain:** Distributed Messaging & Outbound Delivery Guarantees  
**Classification:** Technical Reality & Operational Guarantees  

---

## 1. Fundamental Delivery Semantics: Why "Exactly-Once" is a Fallacy

In distributed network systems spanning client workers, transactional relational databases, and third-party SaaS APIs (Google Workspace Gmail API, SendGrid, Amazon SES, or custom SMTP relays), **distributed exactly-once delivery across unreliable networks is mathematically impossible** (The Two Generals' Problem).

LeadFlow AI makes **zero false claims of "exactly-once delivery"**.

Instead, LeadFlow AI implements **At-Least-Once Job Execution Coupled with Idempotent and Reconcilable Side Effects**.

```text
┌──────────────┐     1. Claim Lease (FOR UPDATE)     ┌────────────────┐
│   SendJob    │ ◄───────────────────────────────── │    Campaign    │
│  PostgreSQL  │                                     │     Worker     │
└──────┬───────┘                                     └───────┬────────┘
       │                                                     │
       │ 4. Commit Status                                    │ 2. Check Idempotency Key
       │    (SENT + msg_id)                                  │    + Transmit Outbound
       ▼                                                     ▼
┌──────────────┐                                     ┌────────────────┐
│ EmailRecord  │                                     │ Email Provider │
│ (Idemp Key)  │                                     │  (Gmail/SMTP)  │
└──────────────┘                                     └────────────────┘
```

---

## 2. The 7 Provider Failure Modes & State Reconciliation

### Mode 1: Normal Acceptance (HTTP 200 / SMTP 250)
- **Sequence**:
  1. Worker claims `SendJob` with a 60-second lease (`status = PROCESSING`).
  2. Worker sends `OutboundMessage` to provider with header `X-Entity-Ref-ID: {idempotency_key}`.
  3. Provider returns `provider_message_id = "<msg-12345@domain.com>"`.
  4. Worker executes `DurableQueue.complete_send_job()`:
     - `EmailRecord.status = SENT`, `provider_message_id = "<msg-12345@domain.com>"`, `sent_at = now()`.
     - `SendJob.status = SENT`, worker lease released.
     - `Lead.status = EMAILED`.
     - `Campaign.total_sent` incremented by 1.
- **Guarantee**: Message sent once; status committed.

---

### Mode 2: Provider Accepts Message, but Response / Network is Lost (The Crash Window)
- **Sequence**:
  1. Worker transmits email; Google Workspace SMTP server accepts the message and queues it for recipient delivery.
  2. Network connection resets, or the worker Linux process is killed (`SIGKILL`, physical host power loss) *before* the HTTP response returns or *before* the worker commits the DB transaction.
  3. `SendJob` remains in `status = PROCESSING` with `lease_expires_at = t + 60s`.
  4. After 60 seconds, `leadflow-maintenance-worker` detects the expired lease and resets `SendJob.status = QUEUED`.
  5. A secondary worker claims the job.
- **Idempotent Reconciliation**:
  - The secondary worker inspects `EmailRecord` using the deterministic `idempotency_key` (`send:{org_id}:{campaign_id}:{lead_id}:{email_record_id}`).
  - If `EmailRecord.provider_message_id` was written by an asynchronous provider webhook or pre-commit log, the worker marks `SendJob.status = SENT` immediately **without re-transmitting to the provider socket**.
  - **Limitation**: In plain SMTP relays without client message deduplication, if the crash happened *after* SMTP socket `DATA` / `CRLF.CRLF` was sent but *before* the client received `250 OK`, an automated retry can produce a duplicate email. This is an inherent physical limitation of the SMTP protocol. With Google Workspace API (OAuth2), deduplication headers mitigate duplicate delivery.

---

### Mode 3: Provider Socket Times Out Before Acceptance
- **Sequence**:
  1. Worker connects to email provider; network packet drops before provider accepts message.
  2. Provider has **not** processed or delivered the email.
  3. Worker catches `TimeoutError` or socket timeout.
  4. Worker marks `SendJob.status = RETRY_WAIT` and schedules next attempt with exponential backoff ($15\text{s} \times 2^{\text{attempt}-1}$).
- **Guarantee**: Message safely retried; no duplicate delivery.

---

### Mode 4: Provider Returns Rate Limit (HTTP 429 / SMTP 451)
- **Sequence**:
  1. Provider rejects with "Rate limit exceeded / Too Many Requests".
  2. Error categorized as `ProviderErrorCode.RATE_LIMIT` with `retryable = True`.
  3. Worker reschedules `SendJob` to `status = RETRY_WAIT`.
  4. Policy engine applies backoff delay (300 seconds).
- **Guarantee**: Account protected from suspension; job queued for delayed dispatch.

---

### Mode 5: Provider Returns Server Temporary Error (HTTP 500 / 503 / SMTP 421)
- **Sequence**:
  1. Provider indicates upstream temporary outage.
  2. Error categorized as `ProviderErrorCode.TEMPORARY_FAILURE` with `retryable = True`.
  3. Job transitions to `status = RETRY_WAIT` up to `max_attempts` (default: 3).
- **Guarantee**: Temporary provider outages do not drop campaigns or corrupt state.

---

### Mode 6: Provider Returns Authentication Failure (HTTP 401 / SMTP 535)
- **Sequence**:
  1. OAuth token revoked, app password invalid, or credentials rotated.
  2. Error categorized as `ProviderErrorCode.AUTH_ERROR` with `retryable = False`.
  3. Worker immediately flags `EmailProviderAccount.is_healthy = False` and records error reason.
  4. Job transitions to `status = FAILED` (dead-letter).
  5. Sending policy engine automatically suppresses further sends across that account.
- **Guarantee**: Halts sending immediately to protect sender domain reputation and alert operators.

---

### Mode 7: Provider Returns Permanent Mailbox Failure (SMTP 550 / 5.1.1 User Unknown)
- **Sequence**:
  1. Recipient address does not exist or domain rejects mail.
  2. Error categorized as `ProviderErrorCode.PERMANENT_FAILURE` with `retryable = False`.
  3. `EmailRecord.status = BOUNCED`.
  4. Recipient email address is automatically added to `suppression_entries` table.
  5. `Campaign.total_bounces` is incremented. If bounce rate exceeds 5%, the circuit breaker pauses the campaign.
- **Guarantee**: Permanent bounces are never retried, preventing domain blacklisting.
