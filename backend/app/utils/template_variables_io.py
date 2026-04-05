"""Template variables: template_variables rows (replaces templates.variables_json)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.template import Template
from app.models.template_variable import TemplateVariable


def replace_template_variables_from_dict(db: Session, template_id: int, variables_json: dict[str, Any] | None) -> None:
    """Persist variable placeholders and optional defaults; clears legacy blob via caller."""
    db.query(TemplateVariable).filter(TemplateVariable.template_id == template_id).delete(synchronize_session=False)
    vj = dict(variables_json or {})
    for key, val in vj.items():
        if not isinstance(key, str) or not key.strip():
            continue
        k = key.strip()
        if k == "variables" and isinstance(val, list):
            for vn in val:
                if isinstance(vn, str) and vn.strip():
                    db.add(
                        TemplateVariable(
                            template_id=template_id,
                            name=vn.strip()[:128],
                            default_value=None,
                        ),
                    )
            continue
        if isinstance(val, (dict, list)):
            db.add(
                TemplateVariable(
                    template_id=template_id,
                    name=k[:128],
                    default_value=json.dumps(val, ensure_ascii=False),
                ),
            )
        else:
            db.add(
                TemplateVariable(
                    template_id=template_id,
                    name=k[:128],
                    default_value=None if val is None else str(val),
                ),
            )


def effective_variables_json_for_api(db: Session, template_id: int) -> dict[str, Any]:
    """Rebuild API shape from template_variables rows (matches legacy variables_json)."""
    rows = (
        db.query(TemplateVariable)
        .filter(TemplateVariable.template_id == template_id)
        .order_by(TemplateVariable.name.asc())
        .all()
    )
    if not rows:
        t = db.query(Template).filter(Template.id == template_id).first()
        if t and dict(t.variables_json or {}):
            replace_template_variables_from_dict(db, template_id, t.variables_json)
            t.variables_json = {}
            db.add(t)
            rows = (
                db.query(TemplateVariable)
                .filter(TemplateVariable.template_id == template_id)
                .order_by(TemplateVariable.name.asc())
                .all()
            )
    if not rows:
        return {}

    # Legacy bad migrate: one row name=variables, default=serialized list
    if len(rows) == 1 and rows[0].name == "variables" and rows[0].default_value:
        try:
            parsed = json.loads(rows[0].default_value)
            if isinstance(parsed, list):
                return {"variables": sorted(str(x) for x in parsed if isinstance(x, str))}
        except json.JSONDecodeError:
            pass

    placeholders: list[str] = []
    fixed: dict[str, Any] = {}
    for r in rows:
        dv = r.default_value
        if dv is None or (isinstance(dv, str) and not dv.strip()):
            placeholders.append(r.name)
            continue
        if isinstance(dv, str):
            s = dv.strip()
            if s.startswith(("{", "[")):
                try:
                    fixed[r.name] = json.loads(s)
                    continue
                except json.JSONDecodeError:
                    pass
            fixed[r.name] = dv
        else:
            fixed[r.name] = dv

    out: dict[str, Any] = {}
    if placeholders:
        out["variables"] = sorted(placeholders)
    out.update(fixed)
    return out
