"""Регресс: батч-персист черновиков (`generate_emails` -> persist_generated_emails ->
bulk_create_email_drafts) должен раскладывать generation_meta_json в ТИПИЗИРОВАННЫЕ колонки
(validation_score / generation_is_valid / prompt_setup_text_used / reasoning_* …).

Баг (2026-07-14): bulk_create_email_drafts делал голый EmailDraft(**row) с легаси-блобом,
не вызывая apply_generation_meta_to_draft — вся батч-генерация волны получала NULL в колонках,
хотя UI/трекинг читают именно их (score/valid показывались пустыми при валидных письмах).
"""


def test_persist_generated_emails_maps_meta_into_typed_columns(db):
    from app.models.project import Project
    from app.models.run import Run
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.services.email_draft_persistence_service import persist_generated_emails

    project = Project(name="persist-meta-test", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="generic_outreach", name="persist-meta-run")
    db.add(run)
    db.commit()
    contact = Contact(
        run_id=run.id, company="Acme", email="x@acme.com", name="Jo", role="CEO",
        status="valid", review_status="approved",
    )
    db.add(contact)
    db.commit()

    step_output = {
        "emails": [
            {
                "contact_id": contact.id,
                "company": "Acme",
                "to": "x@acme.com",
                "subject": "S",
                "body": "B",
                "generation_meta_json": {
                    "reasoning": {"hook": "h", "angle": "a"},
                    "style_mode": "founder",
                    "validation_score": 100,
                    "validation_issues": [],
                    "is_valid": True,
                    "peer_similarity_max": 0.1,
                    "validation_retries": 2,
                    "pipeline_source": "llm",
                    "prompt_setup_text_used": "X" * 7152,
                },
            }
        ]
    }

    res = persist_generated_emails(db, run.id, step_output)
    assert res["saved_drafts"] == 1

    draft = db.query(EmailDraft).filter(EmailDraft.run_id == run.id).first()
    assert draft is not None
    # Типизированные колонки — источник истины (не легаси-блоб)
    assert draft.validation_score == 100.0
    assert draft.generation_is_valid is True
    assert (draft.prompt_setup_text_used or "") != ""
    assert draft.pipeline_source == "llm"
    assert draft.validation_retries == 2
    assert draft.reasoning_hook == "h"
