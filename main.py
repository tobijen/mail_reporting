import os
import json
import time

from utils.mail.web_mail_processor import WebMailProcessorIncremental
from utils.storage.google_sheets_manager import GoogleSheetManager, EmailData


def email_message_to_email_data(email_message):
    """Convert EmailMessage to EmailData."""
    return EmailData(
        subject=str(email_message.subject),
        sender=str(email_message.sender),
        date=email_message.date,
        body="",
    )


def main():
    # Web.de credentials
    web_de_email = os.getenv("WEB_DE_EMAIL")
    web_de_password = os.getenv("WEB_DE_PASSWORD")
    
    if not web_de_email or not web_de_password:
        print("WEB_DE_EMAIL and WEB_DE_PASSWORD environment variables must be set.")
        return
    
    # Google Sheets credentials
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "secrets/google_key_file.json")
    spreadsheet_id = "1JHfKsXFQ71dOAffPq2iwbgWPJKtHUHSjFr8Pu4j_0d8"
    sheet_name = "email_data_raw"
    
    # Initialize managers
    processor = WebMailProcessorIncremental(email=web_de_email, password=web_de_password, batch_size=20)
    manager = GoogleSheetManager(credentials_path)
    
    # Fetch and upload emails in batches
    with processor:
        for batch in processor.fetch_emails(folder="INBOX"):
            if batch:
                # Convert EmailMessage to EmailData
                email_data_batch = [email_message_to_email_data(mail) for mail in batch]
                
                # Append to Google Sheets
                output = manager.append_emails(spreadsheet_id, sheet_name, email_data_batch)
                print(f"Appended batch: {json.dumps(output, indent=2)}")
                print(f"Batch size: {len(batch)}")
                time.sleep(1)  # Sleep to avoid hitting API rate limits
               


if __name__ == "__main__":
    main()