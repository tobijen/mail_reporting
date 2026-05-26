"""
Web.de Mail Processor - A clean interface for accessing and fetching emails from web.de accounts.
"""



import imaplib
import email
from email.header import decode_header
from typing import Optional, List, Dict, Any, Generator
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from dotenv import load_dotenv
import json
from pathlib import Path
import os
import time

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """Represents a single email message."""
    
    subject: str
    sender: str
    recipient: str
    date: Optional[datetime]
    body: str
    #html_body: Optional[str] = None
    attachments: List[str] = None
    
    def __post_init__(self):
        if self.attachments is None:
            self.attachments = []



class EmailState:
    def __init__(self, path: str = "email_state.json"):
        self.path = Path(path)
        self.state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def get_last_fetched_date(self, folder: str) -> Optional[datetime]:
        value = self.state.get(folder, {}).get("last_fetched_date")

        if not value:
            return None

        return datetime.fromisoformat(value)

    def set_last_fetched_date(self, folder: str, date: datetime) -> None:
        self.state.setdefault(folder, {})
        self.state[folder]["last_fetched_date"] = date.isoformat()
        self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2))


class WebMailProcessor:
    """
    A clean interface for accessing and fetching emails from web.de accounts via IMAP.
    
    Usage:
        processor = WebMailProcessor(email="your@web.de", password="your_password")
        processor.connect()
        emails = processor.fetch_emails(folder="INBOX", limit=10)
        processor.disconnect()
    """
    
    # Web.de IMAP server configuration
    IMAP_HOST = "imap.web.de"
    IMAP_PORT = 993
    
    def __init__(self, email: str, password: str, timeout: int = 30, batch_size: int = 10):
        """
        Initialize the WebMailProcessor.
        
        Args:
            email: Your web.de email address
            password: Your web.de password or app-specific password
            timeout: Connection timeout in seconds
            batch_size: Number of emails to fetch in each batch
        """
        self.email = email
        self.password = password
        self.timeout = timeout
        self.batch_size = batch_size
        self.imap_connection: Optional[imaplib.IMAP4_SSL] = None
        self.is_connected = False
    
    def connect(self) -> bool:
        """
        Establish a secure connection to the web.de IMAP server.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.imap_connection = imaplib.IMAP4_SSL(
                self.IMAP_HOST,
                self.IMAP_PORT,
                timeout=self.timeout
            )
            self.imap_connection.login(self.email, self.password)
            self.is_connected = True
            logger.info(f"Successfully connected to {self.IMAP_HOST}")
            return True
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP connection error: {e}")
            self.is_connected = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self) -> None:
        """Close the connection to the IMAP server."""
        if self.imap_connection and self.is_connected:
            try:
                self.imap_connection.close()
                self.imap_connection.logout()
                self.is_connected = False
                logger.info("Disconnected from IMAP server")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
    
    def list_folders(self) -> List[str]:
        """
        Get list of available email folders.
        
        Returns:
            List of folder names
        """
        if not self.is_connected:
            logger.warning("Not connected. Call connect() first.")
            return []
        
        try:
            status, mailboxes = self.imap_connection.list()
            if status == "OK":
                # Parse mailbox names from response
                folders = [
                    mailbox.decode().split('"')[-2]
                    for mailbox in mailboxes
                ]
                return folders
            return []
        except Exception as e:
            logger.error(f"Error listing folders: {e}")
            return []
    
    def fetch_emails(
        self,
        folder: str = "INBOX",
        limit: Optional[int] = None,
        search_criteria: str = "ALL"
    ) -> Generator[List[EmailMessage], None, None]:
        """
        Fetch emails from a specific folder in batches of 10.
        
        Args:
            folder: Name of the folder to fetch from (default: "INBOX")
            limit: Maximum number of emails to fetch (None for all)
            search_criteria: IMAP search criteria (default: "ALL")
        
        Yields:
            Lists of up to 10 EmailMessage objects
        """
        if not self.is_connected:
            logger.warning("Not connected. Call connect() first.")
            return
        
        try:
            # Select the folder
            status, _ = self.imap_connection.select(folder)
            if status != "OK":
                logger.error(f"Failed to select folder: {folder}")
                return
            
            # Search for emails
            status, message_ids = self.imap_connection.search(None, search_criteria)
            if status != "OK":
                logger.error(f"Failed to search emails in {folder}")
                return
            
            # Get message IDs and reverse to get newest first
            msg_ids = message_ids[0].split()
            msg_ids = msg_ids[-limit:] if limit else msg_ids
            
            batch = []
            batch_size = self.batch_size
            
            # Fetch each email
            for mail_id in msg_ids:
                try:
                    status, msg_data = self.imap_connection.fetch(mail_id, "(RFC822)")
                    if status == "OK":
                        email_message = self._parse_email(msg_data[0][1])
                        if email_message:
                            batch.append(email_message)
                            if len(batch) == batch_size:
                                yield batch
                                batch = []
                except Exception as e:
                    logger.warning(f"Error parsing email {mail_id}: {e}")
                    continue
            
            # Yield remaining emails if any
            if batch:
                yield batch
            
            logger.info(f"Fetched emails from {folder} in batches")
        
        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return
    
    def _parse_email(self, raw_email: bytes) -> Optional[EmailMessage]:
        """
        Parse a raw email message into an EmailMessage object.
        
        Args:
            raw_email: Raw email data in bytes
        
        Returns:
            EmailMessage object or None if parsing fails
        """
        try:
            msg = email.message_from_bytes(raw_email)
            
            # Extract basic headers
            subject = self._decode_header(msg.get("Subject", ""))
            sender = msg.get("From", "")
            recipient = msg.get("To", "")
            date_str = msg.get("Date", "")
            
            # Parse date
            date = None
            if date_str:
                try:
                    from email.utils import parsedate_to_datetime
                    date = parsedate_to_datetime(date_str)
                except Exception:
                    pass
            
            # Extract body
            body = ""
            #html_body = None
            
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    
                    if content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        body = payload.decode("utf-8", errors="ignore")
                    elif content_type == "text/html":
                        payload = part.get_payload(decode=True)
                        #html_body = payload.decode("utf-8", errors="ignore")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="ignore")
                else:
                    body = str(msg.get_payload())
            
            return EmailMessage(
                subject=subject,
                sender=sender,
                recipient=recipient,
                date=date,
                body=body,
                #html_body=html_body
            )
        
        except Exception as e:
            logger.error(f"Error parsing email message: {e}")
            return None
    
    @staticmethod
    def _decode_header(header: str) -> str:
        """
        Decode encoded email headers (e.g., RFC 2047).
        
        Args:
            header: The header string to decode
        
        Returns:
            Decoded header string
        """
        if not header:
            return ""
        
        try:
            decoded_parts = []
            for part, encoding in decode_header(header):
                if isinstance(part, bytes):
                    # Some mail providers emit non-standard charset labels like
                    # "unknown-8bit"; treat them as raw bytes and decode safely.
                    charset = (encoding or "utf-8").lower()
                    if charset.startswith("unknown"):
                        charset = "utf-8"

                    try:
                        decoded_parts.append(part.decode(charset, errors="ignore"))
                    except LookupError:
                        decoded_parts.append(part.decode("utf-8", errors="ignore"))
                else:
                    decoded_parts.append(part)
            return "".join(decoded_parts)
        except Exception:
            return header
        
    @staticmethod
    def to_utc_datetime(dt: datetime) -> datetime:
        return dt.replace(tzinfo=timezone.utc)
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


class WebMailProcessorIncremental(WebMailProcessor):

    """
    Extends WebMailProcessor to support incremental 
    fetching of emails based on a persistent state.
    Only returns emails newer than the last fetched date.
    """
    def __init__(self, email: str, password: str, timeout: int = 30, batch_size: int = 10, state_path: str = "email_state.json"):
        super().__init__(email, password, timeout, batch_size)
        self.state = EmailState(state_path)

    def fetch_emails(self, folder: str = "INBOX", limit: Optional[int] = None) -> Generator[List[EmailMessage], None, None]:
        """
        Fetch only new emails since the last fetch using server-side filtering, yielding in batches of 10.
        
        Args:
            folder: Name of the folder to fetch from (default: "INBOX")
            limit: Maximum number of emails to fetch (None for all)
        
        Yields:
            Lists of up to 10 EmailMessage objects that are newer than the last fetched date
        """
        last_fetched_date = self.state.get_last_fetched_date(folder)
        
        # Build search criteria
        search_criteria = "ALL"
        if last_fetched_date is not None:
            # Format date for IMAP SINCE search (DD-MMM-YYYY)
            since_date = last_fetched_date.strftime("%d-%b-%Y")
            search_criteria = f'SINCE "{since_date}"'
            logger.info(f"Fetching emails since {since_date} for folder {folder}")
        
        # Fetch emails using server-side filtering in batches
        for batch in super().fetch_emails(folder=folder, limit=limit, search_criteria=search_criteria):
            # Track the newest email date in this batch for state update
            latest_date = last_fetched_date
            
            for email in batch:
                email_date = self.to_utc_datetime(email.date) if email.date else None
                if email_date is not None and (latest_date is None or email_date > latest_date):
                    logger.info(f"Processing email: {email.subject}")
                    latest_date = email_date
            
            # Update the state with the latest fetched date from this batch
            if latest_date is not None:
                self.state.set_last_fetched_date(folder, latest_date)
            
            yield batch

if __name__ == "__main__":
    print("WebMailProcessor module loaded. Use WebMailProcessor class to access web.de emails.")
    ### create a simple test case to demonstrate usage

    # Example usage (replace with actual credentials for testing)

    processor = WebMailProcessorIncremental(email=os.getenv("WEB_DE_EMAIL"), password=os.getenv("WEB_DE_PASSWORD"))
    with processor:
        for batch in processor.fetch_emails(folder="INBOX"):
            for mail in batch:
                print(mail)
            print(f"Batch size: {len(batch)}")
            time.sleep(1)  # Add a small delay between batches
        
