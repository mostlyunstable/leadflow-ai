"""
Domain & DNS Health Diagnostics Service.
Inspects sender domains for critical email authentication protocols:
1. MX records (Mail Exchanger presence)
2. SPF records (Sender Policy Framework)
3. DMARC records (Domain-based Message Authentication, Reporting, and Conformance)
4. Overall domain health score
"""

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import dns.resolver

logger = logging.getLogger("leadflow.domain")


@dataclass
class DomainHealthReport:
    domain: str
    has_mx: bool
    has_spf: bool
    has_dmarc: bool
    mx_records: List[str]
    spf_record: Optional[str]
    dmarc_record: Optional[str]
    health_score: float
    issues: List[str]
    is_healthy: bool


def inspect_domain_health(domain: str, timeout: float = 3.0) -> DomainHealthReport:
    """
    Perform live DNS query checks for MX, SPF, and DMARC on a target domain.
    Safe against timeouts and network errors.
    """
    domain = domain.strip().lower()
    # Strip protocol if passed
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    domain = domain.split("/", 1)[0].split(":", 1)[0]

    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout

    issues: List[str] = []
    mx_records: List[str] = []
    spf_record: Optional[str] = None
    dmarc_record: Optional[str] = None

    # 1. Query MX records
    try:
        answers = resolver.resolve(domain, "MX")
        for rdata in answers:
            mx_records.append(str(rdata.exchange).rstrip("."))
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        issues.append("No MX records found: Domain cannot receive incoming email/replies")
    except Exception as e:
        issues.append(f"MX lookup failed: {e}")

    # 2. Query SPF (TXT records on domain root)
    try:
        answers = resolver.resolve(domain, "TXT")
        for rdata in answers:
            txt = "".join([b.decode("utf-8", errors="ignore") for b in rdata.strings])
            if txt.startswith("v=spf1"):
                spf_record = txt
                break
        if not spf_record:
            issues.append("Missing SPF record: High risk of outbound emails landing in spam")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        issues.append("Missing SPF record: No TXT records found on domain root")
    except Exception as e:
        issues.append(f"SPF lookup failed: {e}")

    # 3. Query DMARC (TXT record on _dmarc.{domain})
    dmarc_host = f"_dmarc.{domain}"
    try:
        answers = resolver.resolve(dmarc_host, "TXT")
        for rdata in answers:
            txt = "".join([b.decode("utf-8", errors="ignore") for b in rdata.strings])
            if txt.startswith("v=DMARC1"):
                dmarc_record = txt
                break
        if not dmarc_record:
            issues.append("Missing DMARC policy: Modern email providers (Google/Yahoo) mandate DMARC")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        issues.append("Missing DMARC record on _dmarc." + domain)
    except Exception as e:
        issues.append(f"DMARC lookup failed: {e}")

    # Compute health score
    score = 0.0
    if mx_records:
        score += 30.0
    if spf_record:
        score += 35.0
    if dmarc_record:
        score += 35.0

    is_healthy = (score >= 65.0 and bool(mx_records))

    return DomainHealthReport(
        domain=domain,
        has_mx=bool(mx_records),
        has_spf=bool(spf_record),
        has_dmarc=bool(dmarc_record),
        mx_records=mx_records,
        spf_record=spf_record,
        dmarc_record=dmarc_record,
        health_score=score,
        issues=issues,
        is_healthy=is_healthy,
    )
