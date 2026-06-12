"""Deterministic ICP filter (Phase 6): apply the Run's editable criteria (employee band +
icp_criteria_json) to a company's firmographics BEFORE the LLM fit judge — off-ICP rows get
ai_fit_status="incorrect" so the existing ICP gate / UI badge / reject-queue handle them, saving
LLM + OSINT tokens. UNKNOWN signal is never a reject (we only reject on a positive mismatch).
"""

from __future__ import annotations

from typing import Any


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def evaluate_company_icp(firmographics: dict | None, run_setup: Any) -> dict[str, Any]:
    """Return {"verdict": "reject"|"pass"|"unknown", "reason": str}.

    - "reject": a criterion is positively violated (e.g. headcount 40 < min 100) -> mark incorrect.
    - "pass": at least one criterion was checkable and none violated.
    - "unknown": nothing checkable (no firmographics / no criteria) -> leave to the LLM judge.
    firmographics shape (from a firmographics provider): {employee_count:int?, okved:str?,
    okveds:list[str]?, region:str?, revenue:float?, founded_year:int?}.
    """
    fg = firmographics if isinstance(firmographics, dict) else {}
    crit = getattr(run_setup, "icp_criteria_json", None)
    crit = crit if isinstance(crit, dict) else {}

    checked = False

    # Employee band
    emp = fg.get("employee_count")
    if isinstance(emp, int):
        lo = getattr(run_setup, "icp_min_employees", None)
        hi = getattr(run_setup, "icp_max_employees", None)
        if isinstance(lo, int) and emp < lo:
            return {"verdict": "reject", "reason": f"ICP: {emp} сотр. < минимума {lo}"}
        if isinstance(hi, int) and emp > hi:
            return {"verdict": "reject", "reason": f"ICP: {emp} сотр. > максимума {hi}"}
        if isinstance(lo, int) or isinstance(hi, int):
            checked = True

    # OKVED include / exclude (prefix match on the company's OKVED codes)
    okveds = [c for c in (fg.get("okveds") or [fg.get("okved")]) if c]
    okveds_norm = [str(c).strip() for c in okveds]
    excl = crit.get("okved_exclude") or []
    for code in excl:
        if any(o.startswith(str(code)) for o in okveds_norm):
            return {"verdict": "reject", "reason": f"ICP: ОКВЭД {okveds_norm} в исключениях ({code})"}
    incl = crit.get("okved_include") or []
    if incl and okveds_norm:
        checked = True
        if not any(o.startswith(str(code)) for o in okveds_norm for code in incl):
            return {"verdict": "reject", "reason": f"ICP: ОКВЭД {okveds_norm} не входит в {incl}"}

    # Region allow-list (substring match)
    regions = crit.get("regions") or []
    region = _norm(fg.get("region"))
    if regions and region:
        checked = True
        if not any(_norm(r) in region for r in regions):
            return {"verdict": "reject", "reason": f"ICP: регион '{fg.get('region')}' не в {regions}"}

    # Revenue band (in the same units the provider returns)
    rev = fg.get("revenue")
    if isinstance(rev, (int, float)):
        rmin = crit.get("revenue_min")
        rmax = crit.get("revenue_max")
        if isinstance(rmin, (int, float)) and rev < rmin:
            return {"verdict": "reject", "reason": f"ICP: выручка {rev} < {rmin}"}
        if isinstance(rmax, (int, float)) and rev > rmax:
            return {"verdict": "reject", "reason": f"ICP: выручка {rev} > {rmax}"}
        if isinstance(rmin, (int, float)) or isinstance(rmax, (int, float)):
            checked = True

    return {"verdict": "pass" if checked else "unknown", "reason": ""}


def icp_filter_active(run_setup: Any) -> bool:
    """True if the Run has any deterministic ICP criterion set (so we bother fetching firmographics)."""
    if run_setup is None:
        return False
    if getattr(run_setup, "icp_min_employees", None) is not None:
        return True
    if getattr(run_setup, "icp_max_employees", None) is not None:
        return True
    crit = getattr(run_setup, "icp_criteria_json", None)
    return bool(isinstance(crit, dict) and crit)
