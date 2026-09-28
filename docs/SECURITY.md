# LeadFlow AI — Security Architecture & Threat Model

---

## 1. Threat Model & Security Controls

| Threat | Risk Level | Mitigation in LeadFlow AI v2.0 |
| :--- | :--- | :--- |
| **Server-Side Request Forgery (SSRF)** | Critical | `core.security.validate_and_sanitize_target_url` resolves DNS, checks against RFC 1918, loopbacks, link-local metadata (169.254.169.254), and re-validates every redirect hop. |
| **Fail-Open Authentication** | Critical | Removed `if API_KEY and supplied != API_KEY`. Production fails closed. Valid JWT or API key required. |
| **Credential & Token Exposure** | High | All OAuth credentials and refresh tokens are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). Stored in DB, not filesystem. |
| **Multi-Tenant Data Leakage** | Critical | Strict `organization_id` scoping on all queries and mutations via `AuthContext`. |
| **Prompt Injection** | Medium | User-supplied fields (names, company titles) are sanitized via regex before constructing LLM context. |
| **Duplicate Outreach / Spammed Prospects** | High | Deterministic `idempotency_key` and atomic `SendAttempt` records prevent duplicate email delivery on network retries. |
| **Insecure HTTP Headers** | Medium | SecurityHeadersMiddleware enforces HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and Referrer-Policy. |

---

## 2. SSRF Protection Details

Website enrichment crawlers can be weaponized if user-supplied URLs are fetched directly. LeadFlow AI implements defense-in-depth:
1. **Scheme Validation:** Only `http` and `https` allowed.
2. **Pre-flight DNS Resolution:** Resolves target domain to IPv4/IPv6 addresses before opening socket connections.
3. **Blacklisted IP Ranges:** Blocks:
   - `0.0.0.0/8`, `127.0.0.0/8` (Loopback)
   - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (RFC 1918 Private)
   - `169.254.0.0/16` (Link-Local / AWS/GCP Metadata `169.254.169.254`)
   - `100.64.0.0/10` (Carrier-Grade NAT)
   - `fc00::/7`, `fe80::/10` (IPv6 Private / Link-Local)
4. **Redirect Validation:** Redirects are intercepted and each hop re-runs the full SSRF validation check.
5. **Content-Length & Stream Capping:** HTTP streams are capped at 3 MB to prevent Zip Bomb or resource exhaustion attacks.

---

## 3. Cryptography Standards

- **Password Hashing:** PBKDF2 with HMAC-SHA256, 310,000 iterations, 16-byte cryptographically secure random salt (`os.urandom`).
- **Secret Encryption:** Fernet symmetric authenticated encryption. Key derived from 32-byte base64 environment variable `ENCRYPTION_KEY`.
- **JWT Signing:** HMAC-SHA256 with 256-bit secret key.
