"""B-018: инструктивная правка письма из ревью.

Ревьюер (Алексей) комментирует по-русски («убери упоминание беты, короче последний абзац»),
LLM применяет ТОЛЬКО эту правку к тексту — не полный перевод, который молча переписал бы всё
письмо, — и возвращает новый текст вместе с русским переводом результата, чтобы смысл
проверялся по-русски. Ничего не сохраняется: превью применяет отдельный apply-эндпойнт.

B-546: письмо остаётся на языке, на котором оно написано (RU или EN), а не на языке, зашитом
в сетап рана — иначе, например, русское письмо после инструкции возвращалось предпросмотром
по-английски. Для "ru" перевод не запрашивается у модели: subject_ru/body_ru = сам результат.
"""

from __future__ import annotations

from app.services.llm_gateway import complete_prompt_json_object


def instruct_edit_email(subject: str, body: str, instruction: str, *, language: str = "en") -> dict[str, str]:
    """Returns {subject, body, subject_ru, body_ru}; raises ValueError on an unusable LLM reply."""
    lang = "ru" if str(language or "").strip().lower() == "ru" else "en"
    stay_rule = (
        "- The email stays in Russian regardless of the instruction language."
        if lang == "ru"
        else "- The email stays in English regardless of the instruction language."
    )
    prompt = (
        "You are editing a FINALIZED cold outreach email. The reviewer asked for one specific "
        "change (the instruction may be written in Russian).\n\n"
        "Rules:\n"
        "- Apply ONLY the requested change. Every sentence the instruction does not touch must "
        "stay verbatim — same wording, same order. Do not rewrite, shorten or 'improve' anything "
        "beyond the instruction.\n"
        f"{stay_rule}\n"
        "- Never add a sign-off, valediction or sender name (the system appends the signature "
        "automatically). If the instruction would introduce one, end the body with the closing "
        "question instead.\n"
        "- Change the subject only if the instruction explicitly targets it.\n\n"
        f"Reviewer's instruction:\n{instruction}\n\n"
        f"Current subject: {subject}\n\n"
        f"Current body:\n{body}\n\n"
        + (
            'Return ONLY a JSON object like {"subject": "...", "body": "..."} '
            "with the edited Russian email."
            if lang == "ru"
            else 'Return ONLY a JSON object like '
            '{"subject": "...", "body": "...", "subject_ru": "...", "body_ru": "..."} '
            "where subject/body are the edited English email and subject_ru/body_ru are natural "
            "Russian translations of that NEW version for the reviewer's check."
        )
    )
    data = complete_prompt_json_object(prompt, task_kind="draft_instruct_edit")
    subject_out = str(data.get("subject") or "").strip()
    body_out = str(data.get("body") or "").strip()
    if lang == "ru":
        # Письмо уже по-русски — отдельный перевод ревьюеру не нужен, он и так читает оригинал.
        out = {
            "subject": subject_out,
            "body": body_out,
            "subject_ru": subject_out,
            "body_ru": body_out,
        }
    else:
        out = {
            "subject": subject_out,
            "body": body_out,
            "subject_ru": str(data.get("subject_ru") or "").strip(),
            "body_ru": str(data.get("body_ru") or "").strip(),
        }
    if not out["subject"] or not out["body"]:
        raise ValueError("Instruct-edit returned an empty subject or body")
    return out
