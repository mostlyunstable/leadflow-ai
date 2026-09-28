"""
CSV Handler — Parse and import leads from CSV files.
Supports flexible column mapping, encoding fallback, and organization multi-tenancy.
"""

import csv
import io
import logging
from typing import Optional, Union

from database.database import get_session
from database.models import Lead, LeadStatus
from modules.lead_ingestion.validator import LeadValidator

logger = logging.getLogger("leadflow.csv")

COLUMN_ALIASES = {
    "first_name": ["first_name", "firstname", "first name", "fname", "given name"],
    "last_name": ["last_name", "lastname", "last name", "lname", "surname", "family name"],
    "email": ["email", "email address", "e-mail", "mail", "email_address"],
    "company_name": [
        "company_name", "company", "company name", "organization",
        "org", "business", "business name",
    ],
    "website": ["website", "url", "web", "site", "company website", "company_url", "domain"],
    "industry": ["industry", "sector", "vertical", "niche", "business type"],
}


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace("-", "_").replace("  ", " ")


def _map_columns(headers: list[str]) -> dict[str, Optional[int]]:
    normalized = [_normalize_header(h) for h in headers]
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        mapping[field] = None
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized.index(alias)
                break
    return mapping


def parse_csv_content(content: Union[bytes, str], source: str = "csv") -> dict:
    if isinstance(content, bytes):
        decoded = None
        for encoding in ["utf-8", "utf-8-sig", "latin-1", "cp1252"]:
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                pass
        if decoded is None:
            return {
                "leads": [],
                "errors": ["Could not decode CSV file content."],
                "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
            }
        content = decoded

    file_obj = io.StringIO(content)
    csv_reader = csv.reader(file_obj)

    try:
        headers = next(csv_reader)
    except StopIteration:
        return {
            "leads": [],
            "errors": ["CSV file is empty."],
            "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
        }

    if not headers:
        return {
            "leads": [],
            "errors": ["CSV file is empty."],
            "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
        }

    column_map = _map_columns(headers)

    missing_required = []
    for field in ["first_name", "last_name", "email", "company_name"]:
        if column_map.get(field) is None:
            missing_required.append(field)

    if missing_required:
        return {
            "leads": [],
            "errors": [f"Missing required columns: {', '.join(missing_required)}"],
            "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
        }

    raw_leads = []
    errors = []
    for row_num, row in enumerate(csv_reader, start=2):
        try:
            lead_data = {
                "first_name": row[column_map["first_name"]].strip() if column_map["first_name"] is not None and column_map["first_name"] < len(row) else "",
                "last_name": row[column_map["last_name"]].strip() if column_map["last_name"] is not None and column_map["last_name"] < len(row) else "",
                "email": row[column_map["email"]].strip().lower() if column_map["email"] is not None and column_map["email"] < len(row) else "",
                "company_name": row[column_map["company_name"]].strip() if column_map["company_name"] is not None and column_map["company_name"] < len(row) else "",
                "website": (
                    row[column_map["website"]].strip()
                    if column_map["website"] is not None and column_map["website"] < len(row)
                    else None
                ),
                "industry": (
                    row[column_map["industry"]].strip()
                    if column_map["industry"] is not None and column_map["industry"] < len(row)
                    else None
                ),
                "source": source,
            }
            raw_leads.append(lead_data)
        except (IndexError, AttributeError) as e:
            errors.append(f"Row {row_num}: Parse error — {str(e)}")

    validator = LeadValidator()
    result = validator.validate_leads(raw_leads)
    return result


def import_csv_to_db(
    filepath: Optional[str] = None,
    content: Optional[Union[bytes, str]] = None,
    campaign_id: Optional[int] = None,
    organization_id: int = 1,
    source: str = "csv",
) -> dict:
    """
    Parse CSV from file path or content and import valid leads with tenant scoping.
    """
    if filepath:
        with open(filepath, "rb") as f:
            content = f.read()

    if content is None:
        return {"imported": 0, "errors": ["No content provided"], "stats": {"total": 0}}

    parsed = parse_csv_content(content, source=source)

    if not parsed["leads"]:
        return {
            "imported": 0,
            "errors": parsed["errors"],
            "stats": parsed["stats"],
        }

    imported = 0
    db_errors = []

    with get_session() as session:
        for lead_data in parsed["leads"]:
            try:
                # Check for existing lead by email within this organization
                existing = (
                    session.query(Lead)
                    .filter_by(
                        organization_id=organization_id,
                        email=lead_data["email"],
                    )
                    .first()
                )
                if existing:
                    parsed["stats"]["duplicate"] = parsed["stats"].get("duplicate", 0) + 1
                    continue

                lead = Lead(
                    organization_id=organization_id,
                    first_name=lead_data["first_name"],
                    last_name=lead_data["last_name"],
                    email=lead_data["email"],
                    company_name=lead_data["company_name"],
                    website=lead_data.get("website"),
                    industry=lead_data.get("industry"),
                    source=source,
                    status=LeadStatus.NEW,
                    campaign_id=campaign_id,
                )
                session.add(lead)
                imported += 1
            except Exception as e:
                db_errors.append(f"Failed to import {lead_data.get('email', 'unknown')}: {str(e)}")

    logger.info(f"CSV import complete: {imported} leads imported into org {organization_id}")

    return {
        "imported": imported,
        "errors": parsed["errors"] + db_errors,
        "stats": {
            **parsed["stats"],
            "imported": imported,
        },
    }
