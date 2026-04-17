"""
Google Sheets Handler — Import leads from Google Sheets.
Requires a service account with Sheets API access.
"""

import logging
from pathlib import Path
from typing import Optional

from database.database import get_session
from database.models import Lead, LeadStatus
from modules.lead_ingestion.validator import LeadValidator
from config.settings import SHEETS_SERVICE_ACCOUNT_FILE

logger = logging.getLogger(__name__)


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


def fetch_leads_from_sheet(
    spreadsheet_url: str,
    worksheet_name: Optional[str] = None,
) -> dict:
    """
    Fetch lead data from a Google Sheet.
    
    Args:
        spreadsheet_url: Full URL or spreadsheet ID
        worksheet_name: Specific worksheet name (default: first sheet)
        
    Returns:
        dict with keys: leads, errors, stats
    """
    try:
        client = _get_sheets_client()
    except (ImportError, FileNotFoundError) as e:
        return {
            "leads": [],
            "errors": [str(e)],
            "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
        }

    try:
        # Open spreadsheet
        if spreadsheet_url.startswith("http"):
            spreadsheet = client.open_by_url(spreadsheet_url)
        else:
            spreadsheet = client.open_by_key(spreadsheet_url)

        # Select worksheet
        if worksheet_name:
            worksheet = spreadsheet.worksheet(worksheet_name)
        else:
            worksheet = spreadsheet.sheet1

        # Get all records as dicts
        records = worksheet.get_all_records()

        if not records:
            return {
                "leads": [],
                "errors": ["Sheet is empty or has no data rows."],
                "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
            }

        # Map to our schema
        raw_leads = []
        for record in records:
            # Flexible column matching (case-insensitive)
            normalized = {k.strip().lower().replace(" ", "_"): v for k, v in record.items()}

            lead_data = {
                "first_name": str(
                    normalized.get("first_name", normalized.get("firstname", ""))
                ).strip(),
                "last_name": str(
                    normalized.get("last_name", normalized.get("lastname", ""))
                ).strip(),
                "email": str(
                    normalized.get("email", normalized.get("email_address", ""))
                ).strip(),
                "company_name": str(
                    normalized.get("company_name", normalized.get("company", ""))
                ).strip(),
                "website": str(
                    normalized.get("website", normalized.get("url", ""))
                ).strip() or None,
                "industry": str(
                    normalized.get("industry", normalized.get("sector", ""))
                ).strip() or None,
                "source": "sheets",
            }
            raw_leads.append(lead_data)

        # Validate
        validator = LeadValidator()
        result = validator.validate_leads(raw_leads)

        logger.info(
            f"Fetched {len(records)} rows from Google Sheet, "
            f"{result['stats']['valid']} valid leads"
        )

        return result

    except Exception as e:
        logger.error(f"Error fetching from Google Sheets: {e}")
        return {
            "leads": [],
            "errors": [f"Google Sheets error: {str(e)}"],
            "stats": {"total": 0, "valid": 0, "invalid": 0, "duplicate": 0},
        }


def import_sheets_to_db(
    spreadsheet_url: str,
    worksheet_name: Optional[str] = None,
    campaign_id: int = None,
) -> dict:
    """
    Fetch from Google Sheet and import valid leads into the database.
    """
    parsed = fetch_leads_from_sheet(spreadsheet_url, worksheet_name)

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
                existing = session.query(Lead).filter_by(email=lead_data["email"]).first()
                if existing:
                    parsed["stats"]["duplicate"] = parsed["stats"].get("duplicate", 0) + 1
                    continue

                lead = Lead(
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

    logger.info(f"Sheets import complete: {imported} leads imported")

    return {
        "imported": imported,
        "errors": parsed["errors"] + db_errors,
        "stats": {**parsed["stats"], "imported": imported},
    }
