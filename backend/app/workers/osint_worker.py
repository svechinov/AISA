import logging
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.contact import Contact
from app.models.run_company import RunCompany
from app.services.tavily_osint import get_company_dossier, discover_contact_email

logger = logging.getLogger(__name__)

def enrich_crm_data(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    """
    OSINT Worker that acts right after contacts and companies are loaded (e.g. from CRM).
    It gathers business dossiers for companies and attempts to find missing emails.
    """
    logger.info(f"Starting OSINT enrichment for Run {run_id}")
    
    companies = db.query(RunCompany).filter(RunCompany.run_id == run_id).all()
    contacts = db.query(Contact).filter(Contact.run_id == run_id).all()
    
    companies_processed = 0
    emails_found = 0
    
    # 1. Enrich Companies
    for company in companies:
        # We store the dossier in the json_kv field
        kv = company.json_kv or {}
        if not kv.get("osint_dossier"):
            name = company.name or ""
            website = company.website or ""
            if name:
                logger.info(f"Gathering dossier for {name}")
                dossier = get_company_dossier(name, website)
                kv["osint_dossier"] = dossier
                company.json_kv = kv
                flag_modified(company, "json_kv")
                companies_processed += 1

    # 2. Enrich Contacts (missing emails)
    for contact in contacts:
        if contact.status == "needs_discovery" or not contact.email:
            name = contact.name or ""
            company_name = contact.company or ""
            website = contact.website or ""
            if name and company_name:
                logger.info(f"Discovering email for {name} at {company_name}")
                email = discover_contact_email(company_name, website, name)
                if email and "@" in email:
                    contact.email = email
                    contact.status = "valid"
                    emails_found += 1
                else:
                    contact.status = "invalid" # Could not find
                    
    db.commit()
    
    return {
        "status": "enriched",
        "companies_processed": companies_processed,
        "emails_found": emails_found
    }
