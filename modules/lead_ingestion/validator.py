"""
Email Validator & Deduplication Engine.
Validates email format, checks required fields, and removes duplicates.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# RFC 5322 compliant email regex (simplified but robust)
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

# Disposable email domains to reject
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "throwaway.email",
    "fakeinbox.com", "sharklasers.com", "guerrillamailblock.com",
    "grr.la", "guerrillamail.info", "guerrillamail.net", "yopmail.com",
    "trashmail.com", "dispostable.com", "maildrop.cc", "10minutemail.com",
    "temp-mail.org", "tempail.com", "burnermail.io",
}

# Role-based emails to avoid (often bounced or ignored)
ROLE_PREFIXES = {
    "info", "admin", "support", "sales", "contact", "hello", "help",
    "billing", "noreply", "no-reply", "postmaster", "webmaster",
    "abuse", "security", "marketing", "team", "office", "hr",
}


class LeadValidator:
    """Validates and deduplicates lead data."""

    def __init__(self, check_disposable: bool = True, check_role: bool = True):
        self.check_disposable = check_disposable
        self.check_role = check_role

    def validate_email(self, email: str) -> tuple[bool, Optional[str]]:
        """
        Validate a single email address.
        Returns (is_valid, reason_if_invalid).
        """
        if not email:
            return False, "Email is empty"

        email = email.strip().lower()

        # Basic format check
        if not EMAIL_REGEX.match(email):
            return False, f"Invalid email format: {email}"

        # Length check
        if len(email) > 254:
            return False, f"Email too long: {email}"

        # Extract domain and local part
        local, domain = email.rsplit("@", 1)

        # Check domain has at least one dot
        if "." not in domain:
            return False, f"Invalid domain: {domain}"

        # TLD length check
        tld = domain.rsplit(".", 1)[-1]
        if len(tld) < 2:
            return False, f"Invalid TLD: {tld}"

        # Disposable domain check
        if self.check_disposable and domain in DISPOSABLE_DOMAINS:
            return False, f"Disposable email domain: {domain}"

        # Role-based email check (warn but allow)
        if self.check_role and local in ROLE_PREFIXES:
            logger.warning(f"Role-based email detected (allowing): {email}")

        return True, None

    def validate_lead(self, lead_data: dict) -> tuple[bool, list[str]]:
        """
        Validate a single lead's data completeness and quality.
        Returns (is_valid, list_of_issues).
        """
        issues = []

        # Required fields
        if not lead_data.get("first_name", "").strip():
            issues.append("Missing first name")
        if not lead_data.get("last_name", "").strip():
            issues.append("Missing last name")
        if not lead_data.get("company_name", "").strip():
            issues.append("Missing company name")

        # Email validation
        email = lead_data.get("email", "")
        email_valid, email_reason = self.validate_email(email)
        if not email_valid:
            issues.append(email_reason)

        # Normalize website if present
        website = lead_data.get("website", "")
        if website and not website.startswith(("http://", "https://")):
            lead_data["website"] = f"https://{website}"

        return len(issues) == 0, issues

    def validate_leads(self, leads: list[dict]) -> dict:
        """
        Validate a batch of leads, removing duplicates and invalid entries.
        
        Returns:
            dict with keys: leads (valid), rejected (invalid), stats, errors
        """
        valid_leads = []
        rejected = []
        errors = []
        seen_emails = set()
        duplicate_count = 0

        for idx, lead_data in enumerate(leads):
            email = lead_data.get("email", "").strip().lower()

            # Dedup check
            if email in seen_emails:
                duplicate_count += 1
                continue
            seen_emails.add(email)

            # Validate
            is_valid, issues = self.validate_lead(lead_data)

            if is_valid:
                # Normalize data
                lead_data["email"] = email
                lead_data["first_name"] = lead_data["first_name"].strip().title()
                lead_data["last_name"] = lead_data["last_name"].strip().title()
                lead_data["company_name"] = lead_data["company_name"].strip()
                valid_leads.append(lead_data)
            else:
                rejected.append({
                    "row": idx + 1,
                    "email": email,
                    "issues": issues,
                })
                errors.append(f"Row {idx + 1} ({email}): {'; '.join(issues)}")

        stats = {
            "total": len(leads),
            "valid": len(valid_leads),
            "invalid": len(rejected),
            "duplicate": duplicate_count,
        }

        logger.info(
            f"Validation complete: {stats['valid']} valid, "
            f"{stats['invalid']} invalid, {stats['duplicate']} duplicates "
            f"out of {stats['total']} total"
        )

        return {
            "leads": valid_leads,
            "rejected": rejected,
            "stats": stats,
            "errors": errors,
        }
