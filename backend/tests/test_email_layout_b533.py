"""B-533: business-letter layout for outbound email — draft-marked bullet lists (only explicit
markup, no autodetection beyond it), a per-body-language closing greeting for personas that opt in
via the {{CLOSING}} token, and the inline signature logo (cid:asa-logo). Pure-function tests, no DB
(same pattern as test_finale_verbatim_append_b158.py).
"""

from __future__ import annotations

from app.services.outbound_email_body import (
    _BLOCK_GAP,
    SIGNATURE_CLOSING_PLACEHOLDER,
    SIGNATURE_LOGO_CID,
    append_signature_html_after,
    html_to_plain_text_for_mime,
    inline_images_for_email_html,
    normalize_draft_body_for_email_html,
    pick_signature_language,
    plain_text_to_email_html,
    wrap_signature_html_for_email,
)
from app.services.persona_service import ALEXEY_SIGNATURE_HTML, STEPAN_SIGNATURE_HTML

# ---------------------------------------------------------------------------------------------
# plain_text_to_email_html: paragraphs vs. draft-marked lists
# ---------------------------------------------------------------------------------------------


def test_blank_line_splits_into_two_paragraphs():
    html_out = plain_text_to_email_html("Hello Rita,\n\nThanks for reaching out.")
    assert html_out.count("<p") == 2
    assert "<ul" not in html_out


def test_single_newline_stays_br_inside_one_paragraph():
    html_out = plain_text_to_email_html("Line one\nLine two")
    assert html_out.count("<p") == 1
    assert "<br>" in html_out


def test_three_bullet_lines_become_one_list_with_escaping():
    html_out = plain_text_to_email_html("- one <a>\n- two & three\n- four")
    assert html_out.count("<ul") == 1
    assert html_out.count("<li") == 3
    assert "&lt;a&gt;" in html_out
    assert "&amp;" in html_out
    assert "<a>" not in html_out


def test_intro_line_then_bullets_gets_paragraph_before_list():
    html_out = plain_text_to_email_html("Roles open:\n- Unity\n- Unreal\n- QA")
    assert html_out.index("<p") < html_out.index("<ul")
    assert html_out.count("<li") == 3


def test_body_without_bullet_markers_has_no_autodetected_list():
    html_out = plain_text_to_email_html(
        "We grew the team from 30 to 260 people - hundreds of hires along the way.",
    )
    assert "<ul" not in html_out


# ---------------------------------------------------------------------------------------------
# html_to_plain_text_for_mime: list items survive as "- " lines in the MIME plain part
# ---------------------------------------------------------------------------------------------


def test_html_to_plain_preserves_list_items_as_dash_lines():
    html_in = plain_text_to_email_html("- alpha\n- beta")
    plain = html_to_plain_text_for_mime(html_in)
    dash_lines = [ln for ln in plain.split("\n") if ln.strip().startswith("- ")]
    assert dash_lines == ["- alpha", "- beta"]


# ---------------------------------------------------------------------------------------------
# wrap_signature_html_for_email: {{CLOSING}} token -> language-appropriate closing paragraph
# ---------------------------------------------------------------------------------------------


def test_closing_token_english_renders_best_regards_above_border():
    wrapped = wrap_signature_html_for_email(f"{SIGNATURE_CLOSING_PLACEHOLDER}<br>Anastasiya", language="en")
    assert "Best regards," in wrapped
    assert SIGNATURE_CLOSING_PLACEHOLDER not in wrapped
    assert wrapped.index("Best regards,") < wrapped.index("border-top")


def test_closing_token_russian_renders_s_uvazheniem_above_border():
    wrapped = wrap_signature_html_for_email(f"{SIGNATURE_CLOSING_PLACEHOLDER}<br>Anastasiya", language="ru")
    assert "С уважением," in wrapped
    assert SIGNATURE_CLOSING_PLACEHOLDER not in wrapped
    assert wrapped.index("С уважением,") < wrapped.index("border-top")


def test_alexey_signature_unchanged_no_closing_added():
    wrapped = wrap_signature_html_for_email(ALEXEY_SIGNATURE_HTML)
    assert "Best regards" not in wrapped
    assert "С уважением" not in wrapped
    assert wrapped == (
        '<div style="margin-top:14px;padding-top:10px;border-top:1px solid #ddd;'
        'font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.32;color:#333;">'
        f"{ALEXEY_SIGNATURE_HTML}"
        "</div>"
    )


def test_stepan_signature_unchanged_no_closing_added():
    wrapped = wrap_signature_html_for_email(STEPAN_SIGNATURE_HTML)
    assert "Best regards" not in wrapped
    assert "С уважением" not in wrapped
    assert wrapped == (
        '<div style="margin-top:14px;padding-top:10px;border-top:1px solid #ddd;'
        'font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.32;color:#333;">'
        f"{STEPAN_SIGNATURE_HTML}"
        "</div>"
    )


# ---------------------------------------------------------------------------------------------
# inline_images_for_email_html: cid:asa-logo -> one image payload; no cid -> nothing
# ---------------------------------------------------------------------------------------------


def test_inline_images_with_logo_cid_returns_one_png_payload():
    images = inline_images_for_email_html(f'<img src="cid:{SIGNATURE_LOGO_CID}">')
    assert len(images) == 1
    assert images[0]["cid"] == SIGNATURE_LOGO_CID
    assert images[0]["mime_type"] == "image/png"
    assert len(images[0]["content"]) > 0


def test_inline_images_without_logo_cid_returns_empty_list():
    assert inline_images_for_email_html("<p>no logo here</p>") == []


# ---------------------------------------------------------------------------------------------
# pick_signature_language: body language wins over run_language
# ---------------------------------------------------------------------------------------------


def test_pick_signature_language_russian_body():
    assert pick_signature_language("Добрый день, Иван! Спасибо за письмо.") == "ru"


def test_pick_signature_language_english_body():
    assert pick_signature_language("Hello Ivan, thanks for reaching out.") == "en"


def test_pick_signature_language_empty_body_falls_back_to_run_language():
    assert pick_signature_language("", "Russian") == "ru"
    assert pick_signature_language(None, None) == "en"


def test_pick_signature_language_russian_html_body_not_outvoted_by_markup():
    """B-546 (стык с B-544 «Оформление»): тело сохраняется как HTML, и латиница из тегов/
    инлайн-стилей (font-family:Arial,Helvetica,sans-serif, style=, class=...) не должна
    перевешивать кириллицу настоящего текста."""
    html_body = (
        '<p style="margin:0 0 0.55em 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;">'
        "Добрый день! Пишу по поводу вакансии senior backend разработчика в вашей команде."
        "</p>"
        '<ul><li style="margin:0 0 0.25em 0;">Первый пункт про опыт</li>'
        '<li style="margin:0 0 0.25em 0;">Второй пункт про стек</li></ul>'
    )
    assert pick_signature_language(html_body) == "ru"


def test_pick_signature_language_english_html_body_still_english():
    html_body = (
        '<p style="margin:0 0 0.55em 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;">'
        "Hi there! Reaching out about the senior backend engineer role on your team."
        "</p>"
        '<ul><li style="margin:0 0 0.25em 0;">First point about experience</li>'
        '<li style="margin:0 0 0.25em 0;">Second point about the stack</li></ul>'
    )
    assert pick_signature_language(html_body) == "en"


# ---------------------------------------------------------------------------------------------
# Вертикальный ритм (правка Анастасии 17.08): между блоками — пустая строка, не полузазор.
# Первая версия разделяла абзацы 0.55em, и живой адресат прочёл это как слитный текст; та же
# причина делала подпись приклеенной к последнему абзацу. Тест держит ритм, чтобы отступ не
# «оптимизировали» обратно.
# ---------------------------------------------------------------------------------------------


def test_paragraphs_are_separated_by_a_full_blank_line():
    html = plain_text_to_email_html("Первый абзац.\n\nВторой абзац.")
    assert html.count(f"margin:0 0 {_BLOCK_GAP} 0") == 2
    assert "0.55em" not in html


def test_bullet_list_carries_the_same_block_gap():
    html = plain_text_to_email_html("Что берём на себя:\n- поиск;\n- отбор;\n- сопровождение.")
    assert f'<ul style="margin:0 0 {_BLOCK_GAP} 0;' in html


def test_closing_is_preceded_by_a_full_blank_line():
    """Пустая строка перед «Best regards,» приходит отступом последнего абзаца тела —
    отдельного правила у прощания нет, поэтому проверяем стык целиком."""
    body = plain_text_to_email_html("Hello Rita,\n\nLast paragraph of the letter.")
    signature = f"{SIGNATURE_CLOSING_PLACEHOLDER}<br>Anastasiya Zemlyanskaya"
    out = append_signature_html_after(body, signature, language="en")
    assert f'<p style="margin:0 0 {_BLOCK_GAP} 0;line-height:1.45;">Last paragraph' in out
    assert out.index("Last paragraph") < out.index("Best regards,")
    assert "Best regards,</p>" in out


# ---------------------------------------------------------------------------------------------
# Правки Анастасии 17.08 (второй заход, хвост после починки inbox-логирования B-541):
# em dash -> en dash, обращение в приветствии жирным. Оба правила — только для anastasia_style.
# ---------------------------------------------------------------------------------------------


def test_em_dash_becomes_en_dash_when_anastasia_style():
    html_out = plain_text_to_email_html("Мы выросли — сильно.", style_dashes=True)
    assert "—" not in html_out
    assert "Мы выросли – сильно." in html_out


def test_em_dash_untouched_without_anastasia_style():
    html_out = plain_text_to_email_html("Мы выросли — сильно.")
    assert "Мы выросли — сильно." in html_out
    html_out_explicit = plain_text_to_email_html("Мы выросли — сильно.", style_dashes=False)
    assert "Мы выросли — сильно." in html_out_explicit


def test_plain_hyphen_not_confused_with_em_or_en_dash():
    html_out = plain_text_to_email_html(
        "We grew the team from 30 to 260 people - hundreds of hires along the way.",
        style_dashes=True,
    )
    assert "260 people - hundreds" in html_out


def test_hyphen_bullet_marker_survives_dash_normalization():
    html_out = plain_text_to_email_html("Roles open:\n- Unity\n- Unreal", style_dashes=True)
    assert html_out.count("<li") == 2
    assert "Unity" in html_out and "Unreal" in html_out


def test_greeting_name_bolded_cyrillic_comma_form():
    html_out = plain_text_to_email_html("Наталия, здравствуйте!\n\nДальше текст.", style_greeting_bold=True)
    assert "<strong>Наталия</strong>, здравствуйте!" in html_out
    assert "<strong>Дальше" not in html_out


def test_greeting_name_bolded_hello_form():
    html_out = plain_text_to_email_html("Hello Rita,\n\nThanks for reaching out.", style_greeting_bold=True)
    assert "Hello <strong>Rita</strong>," in html_out


def test_greeting_without_confident_name_pattern_is_left_alone():
    for line in ("Добрый день!", "Коллеги,"):
        html_out = plain_text_to_email_html(f"{line}\n\nДальше текст.", style_greeting_bold=True)
        assert "<strong>" not in html_out


def test_normalize_draft_body_wrapper_anastasia_style_applies_both_rules():
    out = normalize_draft_body_for_email_html(
        "Наталия, здравствуйте!\n\nМы выросли — сильно.", anastasia_style=True,
    )
    assert "<strong>Наталия</strong>, здравствуйте!" in out
    assert "—" not in out
    assert "Мы выросли – сильно." in out


def test_normalize_draft_body_wrapper_default_is_unchanged():
    out = normalize_draft_body_for_email_html("Наталия, здравствуйте!\n\nМы выросли — сильно.")
    assert "<strong>" not in out
    assert "Мы выросли — сильно." in out
