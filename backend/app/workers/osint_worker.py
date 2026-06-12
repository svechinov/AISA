import logging
import os
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.contact import Contact
from app.models.run_company import RunCompany
from app.services.tavily_osint import get_company_dossier, discover_contact_email
from app.services.hardcore_osint import gather_raw_entities, find_valid_email, get_domain
from app.utils.run_company_extra import effective_run_company_extra, persist_run_company_extra
from app.workers.contacts_worker import FRESHNESS_MIN_DEFAULT

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

def _apply_icp_size_filter(db: Session, run, companies: list) -> None:
    """Resolve firmographics for each not-yet-judged company and reject those outside the Run's
    ICP band/criteria (employee count + icp_criteria_json). Stores firmographics in the KV and a
    size fact in company_evidence; unknown signal is left for the LLM judge. Never fatal."""
    rs = getattr(run, "run_setup", None)
    from app.services.icp_filter_service import icp_filter_active

    if not icp_filter_active(rs):
        return
    from app.services.firmographics_service import firmographics_configured, lookup_firmographics
    from app.services.icp_filter_service import evaluate_company_icp

    if not firmographics_configured():
        logger.info("ICP filter set but no firmographics provider configured — skipping size gate")
        return

    from datetime import datetime

    for company in companies:
        if company.ai_fit_checked_at is not None:
            continue  # already judged (LLM or prior ICP run) — don't re-resolve
        kv = effective_run_company_extra(db, company)
        fg = kv.get("firmographics")
        if not isinstance(fg, dict):
            try:
                fg = lookup_firmographics(company.name or "", website=company.website or "")
            except Exception as exc:
                logger.warning(f"Firmographics lookup failed for {company.name!r}: {exc}")
                fg = None
            if fg:
                kv["firmographics"] = fg
                persist_run_company_extra(db, company, kv)
        if not fg:
            continue  # unknown size -> let the LLM judge decide
        verdict = evaluate_company_icp(fg, rs)
        if verdict["verdict"] == "reject":
            company.ai_fit_status = "incorrect"
            company.ai_fit_reason = verdict["reason"]
            company.ai_fit_checked_at = datetime.utcnow()
            db.add(company)
            # record the size as evidence so the UI dossier shows why it was filtered
            if isinstance(fg.get("employee_count"), int):
                try:
                    from app.models.company_evidence import CompanyEvidence
                    db.add(CompanyEvidence(
                        run_company_id=company.id, run_id=company.run_id, kind="trigger",
                        fact=f"Численность ~{fg['employee_count']} сотр. (источник: {fg.get('source')})",
                        source_url=None, confidence=None,
                    ))
                except Exception:
                    pass
    db.commit()


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

    # ICP gate (Phase 2): companies the AI-fit judge marked "incorrect" are skipped entirely —
    # no dossier, no contact discovery — so Tavily/LLM tokens are not spent on off-target rows.
    # The verdict comes from analyze-fit endpoints or a manual override; unchecked rows pass.
    # Matching uses the same entity-key machinery as the UI badge (contact_company_ai_fit),
    # so name-spelling/website variants can't make the gate and the badge disagree.
    from app.services.run_companies_status_service import _contact_matches_company, _entity_keys

    # Deterministic ICP filter (Phase 6): when the Run sets an employee band / criteria, resolve
    # firmographics and reject off-ICP companies BEFORE the dossier + LLM judge spend tokens.
    # Unknown size is NOT a reject (left to the LLM judge). Reuses the ai_fit reject machinery.
    _apply_icp_size_filter(db, run, companies)

    rejected_keys: set[str] = set()
    for c in companies:
        if c.ai_fit_status == "incorrect":
            rejected_keys |= _entity_keys({"name": c.name, "website": c.website})
    if rejected_keys:
        logger.info(f"ICP gate: rejected-company keys active ({len(rejected_keys)})")

    # 1. Enrich Companies
    for company in companies:
        if company.ai_fit_status == "incorrect":
            continue
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
                    # persist_run_company_extra also indexes the dossier into company_evidence
                    # (Evidence Store hook at the single dossier-write choke point).
                    persist_run_company_extra(db, company, kv)
                    companies_processed += 1

    # 2. Enrich Contacts (missing emails)
    # Verified-LPR discovery (hardcore: ЕГРЮЛ/dorks + SMTP-verified email) is now the default path.
    # The unverified Tavily email-guess path runs only when osint_discovery_mode is explicitly
    # "api_only" (UI "Cloud Safe"). Runs without a run_setup (e.g. the live import) get the
    # verified path. Either way this loop only touches contacts that lack an email.
    mode = "hardcore"
    if run.run_setup and run.run_setup.osint_discovery_mode == "api_only":
        mode = "api_only"

    for contact in contacts:
        if contact.status == "needs_discovery" or not contact.email:
            name = contact.name or ""
            company_name = contact.company or ""
            website = contact.website or ""

            if _contact_matches_company({"name": company_name, "website": website}, rejected_keys):
                continue  # ICP gate: no discovery spend on contacts of rejected companies
            
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

                if target_name:
                    # Contact already has a person name (e.g. CRM import) — run the verified
                    # path for THAT person: permutations + SMTP against the company domain.
                    # (Before the hardcore default flip these contacts went through the
                    # unverified Tavily guess; never invalidate them without an attempt.)
                    v_email = find_valid_email(target_name, domain, mask)
                    if v_email:
                        contact.email = v_email
                        contact.status = "valid"
                        contact.source_json = {
                            **(contact.source_json or {}),
                            "email_verification": "verified",
                        }
                        emails_found += 1
                    else:
                        contact.status = "invalid"
                elif leaders:
                    # Filter stale contacts (assuming JSON has freshness_score)
                    good_leaders = [l for l in leaders if l.get('freshness_score', 0) >= FRESHNESS_MIN_DEFAULT]
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
                                # v_email is SMTP-verified by find_valid_email (RCPT 250) → record it
                                # so validate keeps it and the Agent B gate admits this contact.
                                contact.source_json = {
                                    **contact.source_json,
                                    "freshness_score": leader.get('freshness_score', 0),
                                    "email_verification": "verified",
                                }
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
                                    source_json={
                                        "freshness_score": leader.get('freshness_score', 0),
                                        "email_verification": "verified",
                                    }
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
