import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.smtp_account import SmtpAccount

logger = logging.getLogger(__name__)

def get_next_available_smtp_account(db: Session) -> SmtpAccount | None:
    """
    Returns the next available SMTP account based on daily limits and least-recently-used (LRU) logic.
    Resets the sent_today counter if a new day has started.
    """
    now = datetime.now(timezone.utc)
    
    accounts = db.query(SmtpAccount).filter(SmtpAccount.is_active == True).all()
    if not accounts:
        return None
        
    # 1. Reset counters if needed
    for account in accounts:
        if account.reset_at is None or now > account.reset_at:
            account.sent_today = 0
            # Reset at the next midnight UTC
            next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            account.reset_at = next_midnight
            db.add(account)
            
    db.commit()

    # 2. Filter accounts that have not reached their limit
    available_accounts = [a for a in accounts if a.sent_today < a.daily_limit]
    
    if not available_accounts:
        logger.warning("All active SMTP accounts have reached their daily limit!")
        return None
        
    # 3. Sort by least recently used (LRU) to distribute load evenly (Round-Robin)
    # Accounts with last_used_at == None get priority
    available_accounts.sort(key=lambda a: a.last_used_at or datetime.min.replace(tzinfo=timezone.utc))
    
    return available_accounts[0]

def increment_account_usage(db: Session, account_id: int):
    """Marks an account as used and increments the daily counter."""
    account = db.query(SmtpAccount).filter(SmtpAccount.id == account_id).first()
    if account:
        account.sent_today += 1
        account.last_used_at = datetime.now(timezone.utc)
        db.commit()
