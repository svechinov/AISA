from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.db import get_db
from app.repositories.email_draft_repo import (
    bulk_set_attached_assets_for_approved_drafts,
    bulk_set_attached_assets_for_pending_drafts,
    delete_email_draft,
    get_email_draft,
    list_email_drafts_by_run,
    list_email_drafts_by_run_paginated,
    update_email_draft_fields,
    update_email_draft_review,
)
from app.utils.attached_asset_ids import normalize_attached_asset_ids
from app.utils.draft_attached_assets import effective_attached_asset_ids_for_email_draft
from app.schemas.email_draft import (
    EmailDraftEditUpdate,
    EmailDraftListRead,
    EmailDraftRead,
    EmailDraftReviewUpdate,
    PaginatedEmailDraftListResponse,
    email_draft_to_list_read,
    email_draft_to_read,
)
from app.workers.email_worker import regenerate_outbound_email_draft

router = APIRouter(prefix="/email-drafts", tags=["email-drafts"])


@router.get("/run/{run_id}", response_model=list[EmailDraftListRead] | PaginatedEmailDraftListResponse)
def list_email_drafts_for_run(
    run_id: int,
    limit: int | None = Query(
        None,
        ge=1,
        le=5000,
        description="If set, response is paginated {items,total,limit,offset}. If omitted, legacy array.",
    ),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Optional search on company, to, subject, body (ilike)."),
    include_body: bool = Query(
        False,
        description="If true, each item includes full `body` (Human UI review). Omit for compact list payloads.",
    ),
    db: Session = Depends(get_db),
):
    if limit is None:
        return [
            email_draft_to_list_read(db, d, include_body=include_body)
            for d in list_email_drafts_by_run(db, run_id)
        ]
    rows, total = list_email_drafts_by_run_paginated(db, run_id, limit=limit, offset=offset, q=q)
    off = max(0, offset)
    return PaginatedEmailDraftListResponse(
        items=[email_draft_to_list_read(db, d, include_body=include_body) for d in rows],
        total=total,
        limit=limit,
        offset=off,
    )


@router.get("/{draft_id}", response_model=EmailDraftRead)
def get_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    return email_draft_to_read(db, draft)


@router.patch("/{draft_id}/review", response_model=EmailDraftRead)
def review_email_draft_route(
    draft_id: int,
    payload: EmailDraftReviewUpdate,
    db: Session = Depends(get_db),
):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    if payload.review_status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="review_status must be approved or rejected")

    updated = update_email_draft_review(
        db=db,
        draft=draft,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )

    # Approving a draft enqueues it for the send-queue worker (which meters pace/window/caps).
    # Best-effort: a queue failure must not fail the review action.
    if payload.review_status == "approved":
        try:
            from app.services.send_queue_service import enqueue_draft

            enqueue_draft(db, updated)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("enqueue_draft after approve failed (draft_id=%s)", draft_id)

    return email_draft_to_read(db, updated)


@router.patch("/{draft_id}/edit", response_model=EmailDraftRead)
def edit_email_draft_route(
    draft_id: int,
    payload: EmailDraftEditUpdate,
    db: Session = Depends(get_db),
):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    updated = update_email_draft_fields(
        db=db,
        draft=draft,
        subject=payload.subject,
        body=payload.body,
        review_notes=payload.review_notes,
        attached_asset_ids=payload.attached_asset_ids,
    )

    # Editing always sets review_status='edited', which validate_outbound_draft_sendable treats as
    # sendable — but that only matters if it also reaches the send queue. Without this, editing a
    # still-pending draft (not yet approved) left it "sendable" in the UI's eyes while permanently
    # absent from send_queue: the worker never sees it, only a manual send would ever go out
    # (backlog B-013 §4). enqueue_draft is idempotent (queued/held/releasing/sent items are left
    # alone), so this is a no-op for a draft that was already approved-and-queued.
    try:
        from app.services.send_queue_service import enqueue_draft

        enqueue_draft(db, updated)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("enqueue_draft after edit failed (draft_id=%s)", draft_id)

    if payload.apply_assets_to_pending_drafts:
        asset_src = (
            payload.attached_asset_ids
            if payload.attached_asset_ids is not None
            else effective_attached_asset_ids_for_email_draft(db, updated)
        )
        bulk_set_attached_assets_for_pending_drafts(
            db,
            updated.run_id,
            normalize_attached_asset_ids(asset_src),
        )
        db.refresh(updated)
    if payload.apply_assets_to_approved_drafts:
        asset_src = (
            payload.attached_asset_ids
            if payload.attached_asset_ids is not None
            else effective_attached_asset_ids_for_email_draft(db, updated)
        )
        bulk_set_attached_assets_for_approved_drafts(
            db,
            updated.run_id,
            normalize_attached_asset_ids(asset_src),
        )
        db.refresh(updated)
    return email_draft_to_read(db, updated)


@router.post("/{draft_id}/regenerate", response_model=EmailDraftRead)
def regenerate_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    try:
        draft = regenerate_outbound_email_draft(db, draft_id)
        return email_draft_to_read(db, draft)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{draft_id}", status_code=204, response_class=Response)
def delete_dead_mailbox_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    """Hard-delete a draft that was marked dead mailbox (Review workspace cleanup)."""
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    if draft.tracking_status != "dead_mailbox":
        raise HTTPException(
            status_code=400,
            detail="Only drafts with tracking dead mailbox can be deleted",
        )
    delete_email_draft(db, draft)
    return Response(status_code=204)


@router.post("/{draft_id}/translate")
def translate_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    """On-demand RU translation for review — Alexey's English is weak, so he reviews with a
    Russian translation alongside the original. Not persisted: re-translate any time on click."""
    from app.services.llm_gateway import complete_prompt_json_object, llm_configured
    from app.services.outbound_email_body import pick_signature_language

    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    # B-546: письмо уже по-русски — переводить его в русский нечем и не нужно (получим мусор).
    if pick_signature_language(draft.body) == "ru":
        return {
            "draft_id": draft_id,
            "subject_ru": draft.subject or "",
            "body_ru": draft.body or "",
            "already_russian": True,
        }

    if not llm_configured():
        raise HTTPException(status_code=503, detail="No LLM API key configured — cannot translate")

    prompt = (
        "Translate the following outreach email into Russian for a reviewer who does not read "
        "English well, so they can judge tone and content before approving. Keep it natural, "
        "not word-for-word; preserve names, companies, and links as-is. "
        'Return a JSON object exactly like {"subject_ru": "...", "body_ru": "..."} and nothing else.\n\n'
        f"Subject: {draft.subject}\n\nBody:\n{draft.body}"
    )
    try:
        data = complete_prompt_json_object(prompt)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Translation failed: {e}") from e

    subject_ru = str(data.get("subject_ru") or "").strip()
    body_ru = str(data.get("body_ru") or "").strip()
    if not subject_ru or not body_ru:
        raise HTTPException(status_code=502, detail="Translation returned an empty result")
    return {"draft_id": draft_id, "subject_ru": subject_ru, "body_ru": body_ru}


class EmailDraftInstructIn(BaseModel):
    """B-018: инструкция ревьюера свободным текстом (обычно по-русски)."""

    instruction: str


class EmailDraftInstructApplyIn(BaseModel):
    """B-018: принятая ревьюером правка (EN-текст из превью instruct-эндпойнта).
    instruction — исходный комментарий: пишется в журнал draft_instruct_log, из которого
    B-031 будет предлагать изменения канона промптов (повторяющиеся правки = сигнал)."""

    subject: str
    body: str
    instruction: str | None = None


@router.post("/{draft_id}/instruct")
def instruct_email_draft_route(
    draft_id: int,
    payload: EmailDraftInstructIn,
    db: Session = Depends(get_db),
):
    """B-018 шаг 1 (превью): применить инструкцию как минимальную правку текста письма.
    Ничего не сохраняет — возвращает новый текст + RU-перевод результата на проверку.

    B-546: язык правки — язык самого письма (`pick_signature_language`), не язык сетапа рана —
    иначе, например, русское письмо после правки возвращалось предпросмотром по-английски."""
    from app.models.run import Run
    from app.services.draft_instruct_edit import instruct_edit_email
    from app.services.llm_gateway import llm_configured
    from app.services.outbound_email_body import pick_signature_language

    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    instruction = (payload.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Instruction is empty")
    if not llm_configured():
        raise HTTPException(status_code=503, detail="No LLM API key configured — cannot edit")

    run = db.get(Run, draft.run_id)
    run_language = getattr(run.run_setup, "language", None) if run else None
    language = pick_signature_language(draft.body, run_language)

    try:
        data = instruct_edit_email(draft.subject or "", draft.body or "", instruction, language=language)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Instruct-edit failed: {e}") from e
    return {"draft_id": draft_id, "language": language, **data}


@router.post("/{draft_id}/instruct-apply", response_model=EmailDraftRead)
def instruct_apply_email_draft_route(
    draft_id: int,
    payload: EmailDraftInstructApplyIn,
    db: Session = Depends(get_db),
):
    """B-018 шаг 2 (применить): сохранить принятую правку и перепрогнать критика на новом тексте.

    ⚠️ Инструктивная правка НЕ меняет статус ревью (в отличие от ручного edit): текстовая правка
    не должна молча одобрять письмо. Черновик, который был `pending`, остаётся `pending` — ревьюер
    всё равно жмёт «Одобрить» отдельно. Уже одобренное/поставленное в очередь письмо остаётся
    таким и переочередывается идемпотентно (слот сохраняется). Так копия батча «одобрение вручную»
    становится правдой (код-ревью 2026-07-11)."""
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    # Статус ДО правки решает, отправляемо ли письмо: только approved/edited идут в очередь.
    prior_review_status = draft.review_status or "pending"
    was_sendable = prior_review_status in ("approved", "edited")

    updated = update_email_draft_fields(
        db=db,
        draft=draft,
        subject=payload.subject,
        body=payload.body,
        review_notes=None,
        attached_asset_ids=None,
    )
    # update_email_draft_fields принудительно ставит 'edited' — для инструктивной правки
    # сохраняем прежний статус ревью, если письмо ещё не было одобрено.
    if not was_sendable:
        updated.review_status = prior_review_status
        db.add(updated)
        db.commit()
        db.refresh(updated)

    # Журнал правок (B-031): копим инструкции с первого дня — не блокирующе.
    if (payload.instruction or "").strip():
        try:
            from app.models.draft_instruct_log import DraftInstructLog

            db.add(
                DraftInstructLog(
                    draft_id=updated.id,
                    run_id=updated.run_id,
                    instruction=payload.instruction.strip(),
                ),
            )
            db.commit()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "draft_instruct_log write failed (draft_id=%s)", draft_id,
            )

    # Перепроверка критиком: правка важнее оценки, поэтому сбой валидации не блокирует сохранение.
    try:
        from app.models.contact import Contact
        from app.models.run import Run
        from app.services.email_validation_service import email_kind_for, validate_outbound_email
        from app.services.outreach_email_pipeline import (
            _serialize_personalization,
            list_outbound_draft_bodies_for_run_excluding_contact,
        )
        from app.services.persona_service import get_run_persona
        from app.services.run_context_service import get_critic_canon_text
        from app.utils.email_draft_generation_meta import critic_taste_column_values

        contact = db.get(Contact, updated.contact_id) if updated.contact_id else None
        if contact is not None:
            pers = _serialize_personalization(db, contact)
            peers = list_outbound_draft_bodies_for_run_excluding_contact(db, updated.run_id, contact.id)
            run = db.get(Run, updated.run_id)
            # B-077: honor the generation contract here too, else a hand-edited no_vacancy draft
            # would be re-judged by the LLM rubric and trip hook_not_grounded again.
            # B-077 etap 2: same per-run canon of judgement as the generation pipeline.
            # B-071: fixed-block exclusion reads the run's persona (decision 4, B-063).
            val = validate_outbound_email(
                payload.subject, payload.body, pers, peers,
                email_kind=email_kind_for(pers), critic_canon=get_critic_canon_text(run),
                persona=get_run_persona(db, run),
                company_name=(contact.company or "").strip() or None,
            )
            updated.validation_score = val.get("score")
            updated.generation_is_valid = val.get("is_valid")
            for k, v in critic_taste_column_values(val).items():
                setattr(updated, k, v)
            db.add(updated)
            db.commit()
            db.refresh(updated)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "re-validate after instruct-apply failed (draft_id=%s)", draft_id,
        )

    # В очередь ставим ТОЛЬКО письмо, которое уже было одобрено (обновляем текст, слот сохраняется).
    # Правка pending-письма НЕ ставит его в очередь — иначе «Принять правку» молча = «Отправить».
    # enqueue_draft идемпотентен; для pending он бы запланировал реальную отправку без одобрения.
    if was_sendable:
        try:
            from app.services.send_queue_service import enqueue_draft

            enqueue_draft(db, updated)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "enqueue_draft after instruct-apply failed (draft_id=%s)", draft_id,
            )

    return email_draft_to_read(db, updated)
