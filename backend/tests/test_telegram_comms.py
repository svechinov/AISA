"""Offline tests for the Telegram comms layer (notify routing + inbound poller)."""

from __future__ import annotations

import json

import pytest

from app.config import settings
from app.services import telegram_notify as tn
from app.services import telegram_poller as tp


# --------------------------------------------------------------------------- registry / routing

def test_parse_topics_preserves_case_and_skips_garbage():
    got = tp.telegram_notify.parse_topics("AI-Biz-OS:2, Content:5 ,ReSpam:8,Общее:1,bad,x:y,:3")
    assert got == {"AI-Biz-OS": 2, "Content": 5, "ReSpam": 8, "Общее": 1}


def test_thread_for_project_is_case_insensitive():
    topics = {"AI-Biz-OS": 2, "Content": 5}
    assert tn.thread_for_project("ai-biz-os", topics) == 2
    assert tn.thread_for_project("CONTENT", topics) == 5
    assert tn.thread_for_project("Finance", topics) is None
    assert tn.thread_for_project(None, topics) is None


def test_project_for_thread_reverse_and_default():
    topics = {"AI-Biz-OS": 2, "Content": 5}
    assert tn.project_for_thread(5, topics) == "Content"
    assert tn.project_for_thread(999, topics) == tn.GENERAL_PROJECT  # unmapped topic
    assert tn.project_for_thread(None, topics) == tn.GENERAL_PROJECT  # DM


# --------------------------------------------------------------------------- send() routing

def test_send_routes_mapped_project_to_group_topic(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_GROUP_CHAT_ID", "-1001")
    monkeypatch.setattr(settings, "TELEGRAM_OWNER_CHAT_ID", "900")
    monkeypatch.setattr(settings, "TELEGRAM_TOPICS", "AI-Biz-OS:2")
    captured: dict = {}
    monkeypatch.setattr(tn, "post", lambda method, payload, **k: captured.update(payload) or True)

    assert tn.send("AI-Biz-OS", "hi") is True
    assert captured["chat_id"] == "-1001"
    assert captured["message_thread_id"] == 2


def test_send_falls_back_to_owner_dm_when_project_unmapped(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_GROUP_CHAT_ID", "-1001")
    monkeypatch.setattr(settings, "TELEGRAM_OWNER_CHAT_ID", "900")
    monkeypatch.setattr(settings, "TELEGRAM_TOPICS", "AI-Biz-OS:2")
    captured: dict = {}
    monkeypatch.setattr(tn, "post", lambda method, payload, **k: captured.update(payload) or True)

    assert tn.send("Finance", "hi") is True
    assert captured["chat_id"] == "900"
    assert "message_thread_id" not in captured


def test_send_without_token_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    assert tn.send("AI-Biz-OS", "hi") is False


# --------------------------------------------------------------------------- classify_message

def test_classify_text():
    kind, text, atts = tp.classify_message({"text": "hello"})
    assert (kind, text, atts) == ("text", "hello", [])


def test_classify_voice_and_document_carry_attachments_and_caption():
    kind, text, atts = tp.classify_message(
        {"voice": {"file_id": "F1", "file_unique_id": "U1"}, "caption": "note"}
    )
    assert kind == "voice" and text == "note"
    assert atts == [{"file_id": "F1", "suggested_name": "voice-U1.ogg"}]

    kind, _, atts = tp.classify_message({"document": {"file_id": "F2", "file_name": "spec.pdf"}})
    assert kind == "document"
    assert atts[0]["suggested_name"] == "spec.pdf"


def test_build_inbox_markdown_has_frontmatter_and_body():
    md = tp.build_inbox_markdown(
        project="Content", sender="Alex (@a)", kind="text",
        text="идея поста", received_iso="2026-07-08T10:00:00Z", attachments=[],
    )
    assert md.startswith("---\nproject: Content\n")
    assert "kind: text" in md
    assert "идея поста" in md
    assert "chat_id:" not in md  # omitted entirely when not passed, not just empty


def test_build_inbox_markdown_includes_chat_id_when_given():
    md = tp.build_inbox_markdown(
        project="Общее", sender="Alex", kind="text",
        text="вопрос", received_iso="2026-07-08T10:00:00Z", attachments=[], chat_id=900,
    )
    assert "chat_id: 900" in md


# --------------------------------------------------------------------------- _process_update

def _wire_process(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TELEGRAM_INBOX_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TELEGRAM_GROUP_CHAT_ID", "-1001")
    monkeypatch.setattr(settings, "TELEGRAM_OWNER_CHAT_ID", "900")
    acks: list[dict] = []
    monkeypatch.setattr(tp.telegram_notify, "post", lambda m, payload, **k: acks.append(payload) or True)
    monkeypatch.setattr(
        tp, "_download_attachment",
        lambda token, file_id, dest_dir, suggested_name: tp._safe(suggested_name),
    )
    return acks


def test_process_update_files_message_and_acks_into_topic(monkeypatch, tmp_path):
    acks = _wire_process(monkeypatch, tmp_path)
    topics = {"Content": 5}
    update = {
        "update_id": 42,
        "message": {
            "chat": {"id": -1001},
            "message_thread_id": 5,
            "from": {"first_name": "Alex", "username": "a"},
            "text": "мысль для контента",
        },
    }
    tp._process_update(update, "T", topics)

    files = list((tmp_path / "Content").glob("*.md"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "мысль для контента" in body and "project: Content" in body

    log = (tmp_path / "log.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(log)["project"] == "Content"

    assert acks and acks[0]["message_thread_id"] == 5
    assert "Content" in acks[0]["text"]


def test_process_update_voice_transcribes_into_body_and_ack(monkeypatch, tmp_path):
    acks = _wire_process(monkeypatch, tmp_path)
    monkeypatch.setattr(tp, "transcribe_audio", lambda path: "расшифрованная мысль")
    topics = {"ReSpam": 4}
    update = {
        "update_id": 50,
        "message": {
            "chat": {"id": -1001},
            "message_thread_id": 4,
            "from": {"first_name": "Alex"},
            "voice": {"file_id": "V1", "file_unique_id": "U9"},
        },
    }
    tp._process_update(update, "T", topics)

    md = next((tmp_path / "ReSpam").glob("*.md")).read_text(encoding="utf-8")
    assert "расшифрованная мысль" in md
    assert "kind: voice" in md
    assert acks and "голос → текст" in acks[0]["text"] and "расшифрованная мысль" in acks[0]["text"]


def test_process_update_voice_transcription_failure_keeps_audio(monkeypatch, tmp_path):
    acks = _wire_process(monkeypatch, tmp_path)
    monkeypatch.setattr(tp, "transcribe_audio", lambda path: None)
    topics = {"ReSpam": 4}
    update = {
        "update_id": 51,
        "message": {"chat": {"id": -1001}, "message_thread_id": 4, "from": {"first_name": "Alex"},
                    "voice": {"file_id": "V2", "file_unique_id": "U8"}},
    }
    tp._process_update(update, "T", topics)
    assert acks and "расшифровать не удалось" in acks[0]["text"]


def test_process_update_general_topic_captures_but_sends_no_ack(monkeypatch, tmp_path):
    """General is a live dialog topic — general_agent (separate service) answers it, not the poller."""
    acks = _wire_process(monkeypatch, tmp_path)
    update = {
        "update_id": 60,
        "message": {"chat": {"id": 900}, "from": {"first_name": "Alex"}, "text": "как дела с очередью?"},
    }
    tp._process_update(update, "T", {})  # owner DM, no thread → «Общее»

    md = next((tmp_path / "Общее").glob("*.md")).read_text(encoding="utf-8")
    assert "как дела с очередью?" in md
    assert "chat_id: 900" in md  # general_agent needs this to reply into the right chat (DM vs group)
    assert acks == []


def test_process_update_ignores_unauthorized_chat(monkeypatch, tmp_path):
    acks = _wire_process(monkeypatch, tmp_path)
    update = {"update_id": 1, "message": {"chat": {"id": 777}, "text": "spam"}}
    tp._process_update(update, "T", {})
    assert list(tmp_path.glob("**/*.md")) == []
    assert acks == []


# --------------------------------------------------------------------------- offset persistence

def test_offset_roundtrip(db):
    assert tp._load_offset(db) == 0
    tp._save_offset(db, 123)
    assert tp._load_offset(db) == 123
    tp._save_offset(db, 456)  # update path
    assert tp._load_offset(db) == 456
