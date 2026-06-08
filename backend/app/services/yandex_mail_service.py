import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

YANDEX_SMTP_SERVER = "smtp.yandex.ru"
YANDEX_SMTP_PORT = 465

YANDEX_IMAP_SERVER = "imap.yandex.ru"
YANDEX_IMAP_PORT = 993

from app.db import SessionLocal
from app.models.system_setting import SystemSetting

def get_yandex_credentials():
    db = SessionLocal()
    try:
        email_setting = db.query(SystemSetting).filter_by(key="yandex_email").first()
        password_setting = db.query(SystemSetting).filter_by(key="yandex_password").first()
        if not email_setting or not password_setting:
            raise ValueError("YANDEX_EMAIL or YANDEX_APP_PASSWORD missing in database settings")
        return email_setting.value, password_setting.value
    finally:
        db.close()

def send_email_yandex(to_address: str, subject: str, body_html: str, from_name: str = None) -> bool:
    email_address, app_password = get_yandex_credentials()
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    if from_name:
        msg["From"] = f"{from_name} <{email_address}>"
    else:
        msg["From"] = email_address
    msg["To"] = to_address
    
    msg.attach(MIMEText(body_html, "html"))
    
    try:
        with smtplib.SMTP_SSL(YANDEX_SMTP_SERVER, YANDEX_SMTP_PORT) as server:
            server.login(email_address, app_password)
            server.send_message(msg)
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to send Yandex email: {e}")
        return False

def check_yandex_inbox_sync():
    """Simple stub for IMAP synchronization"""
    try:
        email_address, app_password = get_yandex_credentials()
        with imaplib.IMAP4_SSL(YANDEX_IMAP_SERVER, YANDEX_IMAP_PORT) as mail:
            mail.login(email_address, app_password)
            mail.select("INBOX")
            # Logic to fetch unread emails and thread them into Ai-Biz-OS DB goes here
            return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed IMAP sync: {e}")
        return False
