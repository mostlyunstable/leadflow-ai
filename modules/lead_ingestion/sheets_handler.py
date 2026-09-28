"""
Google Sheets Handler — Import leads from Google Sheets.
Requires a service account with Sheets API access.
Scoper to organization multi-tenancy.
"""

import logging
from pathlib import Path
from typing import Optional

from database.database import get_session
from database.models import Lead, LeadStatus
from modules.lead_ingestion.validator import LeadValidator
from config.settings import BASE_DIR

SHEETS_SERVICE_ACCOUNT_FILE = str(BASE_DIR / "config" / "credentials" / "sheets_service_account.json")

logger = logging.getLogger("leadflow.sheets")


def _get_sheets_client():
    """Initialize gspread client with service account credentials."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError(
            "Google Sheets integration requires 'gspread' and "
            "'google-auth' packages. Install with: "
            "pip install gspread google-auth"
        )

    creds_path = Path(SHEETS_SERVICE_ACCOUNT_FILE)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Service account file not found: {creds_path}\n"
            "Download from Google Cloud Console → IAM → Service Accounts → Keys"
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    credentials = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return gspread.authorize(credentials)


def import_sheets_to_db(
    spreadsheet_id: str,
    range_name: str = "Sheet1!A:Z",
    campaign_id: Optional[int] = None,
    organization_id: int = 1,
) -> dict:
    """
    Fetch leads from a Google Sheet and import valid rows into the database.
    """
    client = _get_sheets_client()
    sheet = client.open_by_key(spreadsheet_id)
    worksheet = sheet.get_worksheet(0)
    rows = worksheet.get_all_records()

    if not rows:
        return {
            "imported": 0,
            "errors": ["Sheet is empty"],
            "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
        }

    validator = LeadValidator()
    validation_result = validator.validate_leads(rows)
    valid_leads = validation_result["leads"]

    imported = 0
    db_errors = []

    with get_session() as session:
        for lead_data in valid_leads:
            try:
                existing = (
                    session.query(Lead)
                    .filter_by(
                        organization_id=organization_id,
                        email=lead_data["email"],
                    )
                    .first()
                )
                if existing:
                    validation_result["stats"]["duplicate"] = validation_result["stats"].get("duplicate", 0) + 1
                    continue

                lead = Lead(
                    organization_id=organization_id,
                    first_name=lead_data["first_name"],
                    last_name=lead_data["last_name"],
                    email=lead_data["email"],
                    company_name=lead_data["company_name"],
                    website=lead_data.get("website"),
                    industry=lead_data.get("industry"),
                    source="sheets",
                    status=LeadStatus.NEW,
                    campaign_id=campaign_id,
                )
                session.add(lead)
                imported += 1
            except Exception as e:
                db_errors.append(f"Import failed for {lead_data.get('email')}: {str(e)}")

    logger.info(f"Sheets import complete: {imported} leads imported into org {organization_id}")

    return {
        "imported": imported,
        "errors": validation_result["errors"] + db_errors,
        "stats": {**validation_result["stats"], "imported": imported},
    }
