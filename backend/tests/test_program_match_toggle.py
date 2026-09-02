"""Фаза 2, Task 3: per-run выключатель матчера программ (run_setups.program_match_enabled).

Нужен Рамке-2 FG: письмо-веер само перечисляет программы отрасли из промпта, и подстановка
матчером ОДНОЙ программы в слот solution ломает формат. NULL/True = матчер работает, как до фазы.
0 tokens: matcher застаблен и при выключенном гейте не должен вызываться вовсе."""

from __future__ import annotations

import app.services.outreach_email_pipeline as oep
import app.services.program_matcher as pm


class _RS:
    def __init__(self, enabled):
        self.program_match_enabled = enabled
        self.language = "Russian"


class _Run:
    persona_id = None

    def __init__(self, rs):
        self.run_setup = rs


def _stub_matcher(monkeypatch):
    calls = {"n": 0}

    def fake(db, **kwargs):
        calls["n"] += 1
        return {"program_id": 1, "name": "П", "asset_id": None, "format": "f",
                "bullets": ["b"], "solution_text": "Решение матчера", "rationale": "r",
                "fit_score": 90}

    monkeypatch.setattr(pm, "match_program", fake)
    return calls


def test_disabled_skips_the_matcher_entirely(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    assert oep._apply_program_match(fresh_db, _Run(_RS(False)), reasoning, {}) is None
    assert calls["n"] == 0, "выключенный матчер не должен стоить ни одного LLM-вызова"
    assert reasoning["solution"] == "generic"


def test_null_keeps_the_matcher_on(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    match = oep._apply_program_match(fresh_db, _Run(_RS(None)), reasoning, {})

    assert calls["n"] == 1
    assert match and reasoning["solution"] == "Решение матчера"


def test_true_keeps_the_matcher_on(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    oep._apply_program_match(fresh_db, _Run(_RS(True)), reasoning, {})

    assert calls["n"] == 1


def test_run_without_setup_keeps_the_matcher_on(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    oep._apply_program_match(fresh_db, _Run(None), reasoning, {})

    assert calls["n"] == 1
