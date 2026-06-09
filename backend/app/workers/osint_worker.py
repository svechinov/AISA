import logging
import os
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.contact import Contact
from app.models.run_company import RunCompany
from app.services.tavily_osint import get_company_dossier, discover_contact_email
from app.services.hardcore_osint import gather_raw_entities, find_valid_email, get_domain
from app.utils.run_company_extra import effective_run_company_extra, persist_run_company_extra

logger = logging.getLogger(__name__)


def _osint_company_limit() -> int | None:
    """Optional cap on companies enriched per call (cost control, Q19).

    Set env OSINT_MAX_COMPANIES=N to process at most N companies that still lack a dossier.
    Unset/<=0 means no limit. Useful for bounded test runs and to avoid runaway Tavily/LLM spend.
    """
    raw = os.environ.get("OSINT_MAX_COMPANIES", "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
        return n if n > 0 else None
    except ValueError:
        return None

def enrich_crm_data(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    """
    OSINT Worker that acts right after contacts and companies are loaded (e.g. from CRM).
    It gathers business dossiers for companies and attempts to find missing emails.
    """
    logger.info(f"Starting OSINT enrichment for Run {run_id}")
    
    from app.repositories.run_repo import get_run
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    companies = db.query(RunCompany).filter(RunCompany.run_id == run_id).all()
    contacts = db.query(Contact).filter(Contact.run_id == run_id).all()

    companies_processed = 0
    emails_found = 0
    company_limit = _osint_company_limit()
    if company_limit is not None:
        logger.info(f"OSINT company limit active: at most {company_limit} companies this call")

    # 1. Enrich Companies
    for company in companies:
        # We store the dossier in the KV store
        kv = effective_run_company_extra(db, company)
        if not kv.get("osint_dossier"):
            if company_limit is not None and companies_processed >= company_limit:
                logger.info(f"OSINT company limit ({company_limit}) reached — stopping enrichment")
                break
            name = company.name or ""
            website = company.website or ""
            if name:
                logger.info(f"Gathering dossier for {name}")
                dossier = get_company_dossier(name, website, run=run)
                # Persist only a real dossier. On transient failure get_company_dossier returns an
                # error string ('{"error": ...}') or a "not configured" notice — persisting it would
                # cache the failure as the dossier and permanently block retries. Skip → retry later.
                bad = (not dossier) or ('"error"' in dossier) or dossier.startswith("Tavily API key not configured")
                if bad:
                    logger.warning(f"OSINT dossier for {name} failed/empty — not persisted (will retry next run)")
                else:
                    kv["osint_dossier"] = dossier
                    persist_run_company_extra(db, company, kv)
                    companies_processed += 1

    # 2. Enrich Contacts (missing emails)
    mode = "api_only"
    if run.run_setup and run.run_setup.osint_discovery_mode == "hardcore":
        mode = "hardcore"

    for contact in contacts:
        if contact.status == "needs_discovery" or not contact.email:
            name = contact.name or ""
            company_name = contact.company or ""
            website = contact.website or ""
            
            if mode == "hardcore":
                domain = get_domain(website)
                if not domain:
                    logger.warning(f"No domain for {company_name}, skipping hardcore OSINT")
                    contact.status = "invalid"
                    continue
                
                logger.info(f"HARDCORE OSINT: Discovering contact for {company_name}")
                custom_prompt = run.run_setup.deep_osint_prompt if run.run_setup else None
                raw_data = gather_raw_entities(company_name, domain, custom_prompt=custom_prompt)
                leaders = raw_data.get('leaders', [])
                mask = raw_data.get('email_mask_guess')
                
                target_name = name
                target_role = contact.role or ""
                
                if not target_name and leaders:
                    # Filter stale contacts (assuming JSON has freshness_score)
                    good_leaders = [l for l in leaders if l.get('freshness_score', 0) >= 30]
                    if not good_leaders:
                        good_leaders = leaders
                        
                    found_any = False
                    for idx, leader in enumerate(good_leaders[:3]):
                        t_name = leader['name']
                        t_role = leader['role']
                        v_email = find_valid_email(t_name, domain, mask)
                        if v_email:
                            found_any = True
                            emails_found += 1
                            if not contact.email and contact.status != "valid":
                                # Update existing empty contact
                                contact.name = t_name
                                contact.role = t_role
                                contact.email = v_email
                                contact.status = "valid"
                                contact.source_json = {**contact.source_json, "freshness_score": leader.get('freshness_score', 0)}
                            else:
                                # Create new contact for parallel outreach
                                new_contact = Contact(
                                    run_id=run_id,
                                    collect_index=db.query(Contact).filter_by(run_id=run_id).count() + 1,
                                    company=company_name,
                                    website=website,
                                    name=t_name,
                                    role=t_role,
                                    email=v_email,
                                    status="valid",
                                    source_json={"freshness_score": leader.get('freshness_score', 0)}
                                )
                                db.add(new_contact)
                                
                    if not found_any:
                        contact.status = "invalid"
                else:
                    contact.status = "invalid"

            else:
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
