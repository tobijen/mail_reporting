import json
import os

from utils.transformations.transformation_logic import ExtractedEmailAddress, extract_email_addresses, transform_google_sheet_email_addresses
from utils.storage.google_sheets_manager import GoogleSheetManager

if __name__ == "__main__":
    from utils.storage.google_sheets_manager import GoogleSheetManager
    #from storage.google_sheets_manager import GoogleSheetManager

    # Google Sheets credentials
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "secrets/google_key_file.json")
    spreadsheet_id = "1JHfKsXFQ71dOAffPq2iwbgWPJKtHUHSjFr8Pu4j_0d8"
    sheet_name = "email_data_raw"

    spreadsheet_id = os.getenv(
        "GOOGLE_SPREADSHEET_ID",
        "1JHfKsXFQ71dOAffPq2iwbgWPJKtHUHSjFr8Pu4j_0d8",
    )
    source_sheet_name = os.getenv("SOURCE_SHEET_NAME", "email_data_raw")
    target_sheet_name = os.getenv("TARGET_SHEET_NAME", "email_addresses")

    sheet_manager = GoogleSheetManager(credentials_path)
    result = transform_google_sheet_email_addresses(
        manager=sheet_manager,
        spreadsheet_id=spreadsheet_id,
        source_sheet_name=source_sheet_name,
        target_sheet_name=target_sheet_name,
    )
    print(json.dumps(result, indent=2))