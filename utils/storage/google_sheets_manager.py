from __future__ import annotations

from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError


@dataclass
class EmailData:
    """Represents a single email message."""

    subject: str
    sender: str
    date: Optional[date | datetime]
    body: str
    _uploaded_at: datetime = field(default_factory=datetime.now)
    #html_body: Optional[str] = None
    #attachments: List[str] = None


class GoogleSheetManager:
    SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
    EMAIL_HEADERS = ["subject", "sender", "date", "body", "_uploaded_at"]
    EMAIL_KEY_HEADERS = ["subject", "sender", "date", "body"]

    def __init__(self, credentials_path: str | Path):
        self.credentials_path = Path(credentials_path)
        self.service = self._authenticate()

    def _authenticate(self) -> Resource:
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Google credentials file not found: {self.credentials_path}"
            )

        credentials = Credentials.from_service_account_file(
            str(self.credentials_path),
            scopes=self.SCOPES,
        )
        return build("sheets", "v4", credentials=credentials)

    def append_email(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        email_data: EmailData,
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        return self.append_emails(
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
            emails=[email_data],
            value_input_option=value_input_option,
        )

    def append_emails(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        emails: list[EmailData],
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        if not emails:
            return {
                "appended_count": 0,
                "skipped_count": 0,
                "total_input_count": 0,
            }

        header_range = f"{sheet_name}!A1:E1"
        append_range = f"{sheet_name}!A:E"

        self._ensure_email_headers(spreadsheet_id, header_range)
        existing_values = self._get_values(spreadsheet_id, append_range)
        existing_keys: set[tuple[str, str, str, str]] = set()
        for row in existing_values[1:]:
            row_key = self._row_to_key(row)
            if row_key is not None:
                existing_keys.add(row_key)

        values: list[list[str]] = []
        pending_keys: set[tuple[str, str, str, str]] = set()
        for email in emails:
            email_key = self._email_to_key(email)
            if email_key in existing_keys or email_key in pending_keys:
                continue

            values.append(self._email_to_row(email))
            pending_keys.add(email_key)

        if not values:
            return {
                "appended_count": 0,
                "skipped_count": len(emails),
                "total_input_count": len(emails),
            }

        response = self._append_values(
            spreadsheet_id=spreadsheet_id,
            range_name=append_range,
            values=values,
            value_input_option=value_input_option,
        )
        response["appended_count"] = len(values)
        response["skipped_count"] = len(emails) - len(values)
        response["total_input_count"] = len(emails)
        return response

    def get_values(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> list[list[Any]]:
        return self._get_values(spreadsheet_id, range_name)

    def set_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        return self._set_values(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            values=values,
            value_input_option=value_input_option,
        )

    def append_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        return self._append_values(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            values=values,
            value_input_option=value_input_option,
        )

    def clear_values(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> dict[str, Any]:
        try:
            response = (
                self.service.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    body={},
                )
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(
                f"Failed to clear '{range_name}' in spreadsheet "
                f"'{spreadsheet_id}'."
            ) from error

        return response

    def ensure_sheet_exists(
        self,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> None:
        try:
            spreadsheet = (
                self.service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id)
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(
                f"Failed to fetch spreadsheet '{spreadsheet_id}'."
            ) from error

        for sheet in spreadsheet.get("sheets", []):
            title = sheet.get("properties", {}).get("title")
            if title == sheet_name:
                return

        try:
            (
                self.service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "addSheet": {
                                    "properties": {
                                        "title": sheet_name,
                                    }
                                }
                            }
                        ]
                    },
                )
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(
                f"Failed to create sheet '{sheet_name}' in spreadsheet "
                f"'{spreadsheet_id}'."
            ) from error

    def _get_values(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> list[list[Any]]:
        try:
            response = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_name)
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(
                f"Failed to fetch data from '{range_name}' in spreadsheet "
                f"'{spreadsheet_id}'."
            ) from error

        return response.get("values", [])

    def _set_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        body = {"values": values}

        try:
            response = (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input_option,
                    body=body,
                )
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(
                f"Failed to update '{range_name}' in spreadsheet "
                f"'{spreadsheet_id}'."
            ) from error

        return response

    def _append_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        body = {"values": values}

        try:
            response = (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input_option,
                    insertDataOption="INSERT_ROWS",
                    body=body,
                )
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(
                f"Failed to append email data to '{range_name}' in spreadsheet "
                f"'{spreadsheet_id}'."
            ) from error

        return response

    @staticmethod
    def _format_datetime(value: Optional[datetime]) -> str:
        if value is None:
            return ""
        return value.isoformat()

    def _email_to_row(self, email_data: EmailData) -> list[str]:
        return [
            email_data.subject,
            email_data.sender,
            self._format_datetime(email_data.date),
            email_data.body,
            self._format_datetime(email_data._uploaded_at),
        ]

    def _email_to_key(self, email_data: EmailData) -> tuple[str, str, str, str]:
        return (
            email_data.subject,
            email_data.sender,
            self._format_datetime(email_data.date),
            email_data.body,
        )

    def _row_to_key(self, row: list[Any]) -> Optional[tuple[str, str, str, str]]:
        if len(row) < len(self.EMAIL_KEY_HEADERS):
            return None

        return tuple(str(value) for value in row[: len(self.EMAIL_KEY_HEADERS)])

    def _ensure_email_headers(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> None:
        existing_values = self._get_values(spreadsheet_id, range_name)
        if existing_values:
            first_row = existing_values[0]
            if first_row[: len(self.EMAIL_HEADERS)] == self.EMAIL_HEADERS:
                return

        self._set_values(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            values=[self.EMAIL_HEADERS],
        )


if __name__ == "__main__":
    import os
    import json

    # Example usage
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "secrets/google_key_file.json")
    print(f"Using credentials from: {credentials_path}")
    spreadsheet_id = "1JHfKsXFQ71dOAffPq2iwbgWPJKtHUHSjFr8Pu4j_0d8"
    sheet_name = "email_data_raw"

    manager = GoogleSheetManager(credentials_path)

    email_data = EmailData(
        subject="Test Email",
        sender="test@example.com",
        date=date.today() - timedelta(days=1),
        body="This is a test email."
    )
   
    output = manager.append_email(spreadsheet_id, sheet_name, email_data)
    print(json.dumps(output, indent=2))
