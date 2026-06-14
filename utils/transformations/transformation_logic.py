from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.storage.google_sheets_manager import GoogleSheetManager



@dataclass(frozen=True)
class ExtractedEmailAddress:
    source_row: int
    email_address: str
    # found_in: str
    subject: str
    sender: str
    date: str

    def to_row(self) -> list[str | int]:
        return [
            self.source_row,
            self.email_address,
            # self.found_in,
            self.subject,
            self.sender,
            self.date,
        ]


def extract_email_addresses(text: Any) -> list[str]:

    email_address_pattern = re.compile(
        r"(?<![A-Za-z0-9._%+-])"
        r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
        r"(?![A-Za-z0-9._%+-])"
    )

    if text is None:
        return []

    normalized_addresses: list[str] = []
    seen: set[str] = set()
    for match in email_address_pattern.finditer(str(text)):
        address = match.group(1).strip().lower()
        if address not in seen:
            normalized_addresses.append(address)
            seen.add(address)

    return normalized_addresses


def _get_cell(row: list[Any], index: int) -> str:
    if index >= len(row):
        return ""
    return str(row[index])


def transform_raw_email_rows(
    rows: list[list[Any]],
    search_columns: tuple[str, ...] = ("sender", "body", "subject"),
) -> list[ExtractedEmailAddress]:
    if not rows:
        return []

    headers = [str(header).strip().lower() for header in rows[0]]
    column_indexes = {header: index for index, header in enumerate(headers)}
    missing_columns = [
        column for column in ("subject", "sender", "date") if column not in column_indexes
    ]
    if missing_columns:
        raise ValueError(
            "Missing required source columns: " + ", ".join(missing_columns)
        )

    searchable_columns = [
        column for column in search_columns if column in column_indexes
    ]
    if not searchable_columns:
        raise ValueError(
            "None of the configured search columns exist in the source sheet."
        )

    extracted: list[ExtractedEmailAddress] = []
    seen: set[tuple[int, str]] = set()

    for row_number, row in enumerate(rows[1:], start=2):
        subject = _get_cell(row, column_indexes["subject"])
        sender = _get_cell(row, column_indexes["sender"])
        date = _get_cell(row, column_indexes["date"])

        for column in searchable_columns:
            cell_value = _get_cell(row, column_indexes[column])
            for address in extract_email_addresses(cell_value):
                key = (row_number, address)
                if key in seen:
                    continue

                extracted.append(
                    ExtractedEmailAddress(
                        source_row=row_number,
                        email_address=address,
                        #found_in=column,
                        subject=subject,
                        sender=sender,
                        date=date,
                    )
                )
                seen.add(key)

    return extracted


def transform_google_sheet_email_addresses(
    manager: GoogleSheetManager,
    spreadsheet_id: str,
    source_sheet_name: str,
    target_sheet_name: str,
    search_columns: tuple[str, ...] = ("sender", "body", "subject"),
) -> dict[str, int]:
    
    extracted_email_headers = [
        "source_row",
        "email_address",
        # "found_in",
        "subject",
        "sender",
        "date",
    ]


    source_rows = manager.get_values(
        spreadsheet_id=spreadsheet_id,
        range_name=f"{source_sheet_name}!A:Z",
    )
    extracted_addresses = transform_raw_email_rows(
        source_rows,
        search_columns=search_columns,
    )

    # check sheet exists
    manager.ensure_sheet_exists(
        spreadsheet_id=spreadsheet_id,
        sheet_name=target_sheet_name,
    )

    # clear values in sheet
    manager.clear_values(
        spreadsheet_id=spreadsheet_id,
        range_name=f"{target_sheet_name}!A:F",
    )

    # write new values to sheet
    manager.set_values(
        spreadsheet_id=spreadsheet_id,
        range_name=f"{target_sheet_name}!A:F",
        values=[extracted_email_headers]
        + [address.to_row() for address in extracted_addresses],
    )

    return {
        "source_rows": max(len(source_rows) - 1, 0),
        "extracted_count": len(extracted_addresses),
    }



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
