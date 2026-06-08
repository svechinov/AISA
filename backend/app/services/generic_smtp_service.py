import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Any
import logging

from app.models.smtp_account import SmtpAccount

logger = logging.getLogger(__name__)

def send_email_via_smtp_account(
    account: SmtpAccount,
    to_address: str, 
    subject: str, 
    body_html: str, 
    from_name: str = None,
    attachments: list[dict[str, Any]] | None = None
) -> bool:
    """Sends an email using the provided SMTP account credentials."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    if from_name:
        msg["From"] = f"{from_name} <{account.email}>"
    else:
        msg["From"] = account.email
    msg["To"] = to_address
    
    msg.attach(MIMEText(body_html, "html"))
    
    if attachments:
        for att in attachments:
            try:
                part = MIMEApplication(att["content"], Name=att["filename"])
                part['Content-Disposition'] = f'attachment; filename="{att["filename"]}"'
                msg.attach(part)
            except Exception as e:
                logger.error(f"Failed to attach file {att.get('filename')}: {e}")

    try:
        # Many modern SMTP servers use STARTTLS on 587 or SSL on 465
        # Assuming SSL on 465 if port is 465, otherwise STARTTLS
        if account.smtp_port == 465:
            with smtplib.SMTP_SSL(account.smtp_server, account.smtp_port) as server:
                server.login(account.email, account.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(account.smtp_server, account.smtp_port) as server:
                server.starttls()
                server.login(account.email, account.password)
                server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Failed to send email via {account.smtp_server} ({account.email}): {e}")
        return False
