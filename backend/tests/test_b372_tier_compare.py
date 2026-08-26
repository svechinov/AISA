"""B-372: offline unit tests for the metric-counting functions in scripts/b372_tier_compare.py —
schema checks, grounding (hallucinated-url detection), tier agreement, and the standard/cheap/kimi
merge in cmd_compare. Synthetic data only, no network, no LLM, no DB writes."""

import json

import scripts.b372_tier_compare as tc


# --- schema checks --------------------------------------------------------------------------


def test_dossier_schema_ok_valid():
    resp = {
        "hypotheses": ["h1"],
        "triggers": ["t1"],
        "evidence": [{"fact": "f", "source_url": "https://x", "confidence_score": 90}],
    }
    assert tc._dossier_schema_ok(resp)


def test_dossier_schema_ok_missing_evidence():
    assert not tc._dossier_schema_ok({"hypotheses": [], "triggers": []})


def test_dossier_schema_ok_wrong_url_type():
    resp = {"hypotheses": [], "triggers": [], "evidence": [{"fact": "f", "source_url": 123, "confidence_score": 90}]}
    assert not tc._dossier_schema_ok(resp)


def test_dossier_schema_ok_bool_confidence_rejected():
    # bool is a subclass of int in Python — must not slip through the numeric check.
    resp = {"hypotheses": [], "triggers": [], "evidence": [{"fact": "f", "source_url": "https://x", "confidence_score": True}]}
    assert not tc._dossier_schema_ok(resp)


def test_dossier_schema_ok_not_a_dict():
    assert not tc._dossier_schema_ok("not a dict")


def test_vacancy_schema_ok_valid():
    resp = {"is_hiring": True, "open_roles": [{"role": "Engineer", "evidence_url": "https://x"}], "summary": "s"}
    assert tc._vacancy_schema_ok(resp)


def test_vacancy_schema_ok_bad_is_hiring_type():
    assert not tc._vacancy_schema_ok({"is_hiring": "yes", "open_roles": []})


def test_vacancy_schema_ok_role_missing_evidence_url():
    resp = {"is_hiring": True, "open_roles": [{"role": "Engineer"}]}
    assert not tc._vacancy_schema_ok(resp)


def test_lpr_schema_ok_all_fields_present():
    resp = {f: "x" for f in tc.LPR_FIELDS}
    assert tc._lpr_schema_ok(resp)


def test_lpr_schema_ok_missing_field():
    resp = {f: "x" for f in tc.LPR_FIELDS[:-1]}
    assert not tc._lpr_schema_ok(resp)


# --- grounding (hallucinated urls) ----------------------------------------------------------


def test_grounding_ratio_all_matched():
    matched, total = tc._grounding_ratio(["https://a", "https://b"], ["https://a", "https://b", "https://c"])
    assert (matched, total) == (2, 2)


def test_grounding_ratio_hallucinated_url():
    matched, total = tc._grounding_ratio(["https://a", "https://made-up"], ["https://a"])
    assert (matched, total) == (1, 2)


def test_grounding_ratio_empty_response_urls():
    assert tc._grounding_ratio([], ["https://a"]) == (0, 0)


def test_dossier_urls_extracts_source_urls_only():
    resp = {"evidence": [{"source_url": "https://a"}, {"source_url": "https://b"}, {"fact": "no url"}]}
    assert tc._dossier_urls(resp) == ["https://a", "https://b"]


def test_dossier_urls_non_dict_returns_empty():
    assert tc._dossier_urls("nope") == []


def test_vacancy_urls_extracts_evidence_urls_only():
    resp = {"open_roles": [{"evidence_url": "https://a"}, {"role": "x"}]}
    assert tc._vacancy_urls(resp) == ["https://a"]


# --- tier agreement --------------------------------------------------------------------------


def test_tier_agreement_match_true():
    assert tc._tier_agreement({"is_hiring": True}, {"is_hiring": True}) is True


def test_tier_agreement_match_false():
    assert tc._tier_agreement({"is_hiring": False}, {"is_hiring": False}) is True


def test_tier_agreement_mismatch():
    assert tc._tier_agreement({"is_hiring": True}, {"is_hiring": False}) is False


def test_tier_agreement_none_when_key_missing():
    assert tc._tier_agreement({"foo": 1}, {"is_hiring": True}) is None


def test_tier_agreement_none_when_not_dict():
    assert tc._tier_agreement("error string", {"is_hiring": True}) is None


# --- misc helper -----------------------------------------------------------------------------


def test_pct_helper():
    assert tc._pct(1, 4) == "25%"
    assert tc._pct(0, 0) == "n/a"


# --- cmd_compare merge: topping up one arm must not lose earlier arms --------------------------


def _fake_tasks():
    return [
        {"kind": "vacancy", "company": "Acme", "prompt": "p-vacancy", "corpus_urls": ["https://acme.example/careers"]},
        {"kind": "dossier", "company": "Acme", "prompt": "p-dossier", "corpus_urls": ["https://acme.example"]},
    ]


def test_compare_merge_preserves_earlier_arms(monkeypatch, tmp_path):
    corpora_path = tmp_path / "b372_corpora.json"
    results_path = tmp_path / "b372_results.json"
    corpora_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tc, "CORPORA_PATH", corpora_path)
    monkeypatch.setattr(tc, "RESULTS_PATH", results_path)
    monkeypatch.setattr(tc, "_build_tasks", lambda corpora: _fake_tasks())

    calls: list[tuple[str, str]] = []

    def fake_run_arm(arm, prompt):
        calls.append((arm, prompt))
        return {"arm": arm, "prompt": prompt}

    monkeypatch.setattr(tc, "_run_arm", fake_run_arm)

    # First run: only standard + cheap (money already spent, standard/cheap comparison already
    # under way when this test's scenario starts).
    tc.cmd_compare(yes=True, arms=["standard", "cheap"])
    written = json.loads(results_path.read_text(encoding="utf-8"))
    assert len(written) == 2
    by_key_1 = {(e["kind"], e["company"]): e for e in written}
    for t in _fake_tasks():
        entry = by_key_1[(t["kind"], t["company"])]
        assert entry["standard"] == {"ok": True, "response": {"arm": "standard", "prompt": t["prompt"]}, "elapsed_s": entry["standard"]["elapsed_s"]}
        assert entry["cheap"] == {"ok": True, "response": {"arm": "cheap", "prompt": t["prompt"]}, "elapsed_s": entry["cheap"]["elapsed_s"]}
        assert "kimi" not in entry

    # Second run: top up only kimi (--arms kimi). standard/cheap responses recorded above must
    # survive untouched, and no standard/cheap calls must happen again (no re-billing).
    calls.clear()
    tc.cmd_compare(yes=True, arms=["kimi"])
    written2 = json.loads(results_path.read_text(encoding="utf-8"))
    assert len(written2) == 2
    assert set(calls) == {("kimi", "p-vacancy"), ("kimi", "p-dossier")}
    by_key = {(e["kind"], e["company"]): e for e in written2}
    for (kind, company), entry in by_key.items():
        assert entry["kimi"]["ok"] is True
        assert entry["kimi"]["response"]["arm"] == "kimi"
        # standard/cheap untouched from the first cmd_compare call
        assert entry["standard"]["response"]["arm"] == "standard"
        assert entry["cheap"]["response"]["arm"] == "cheap"


def test_compare_dry_run_writes_nothing(monkeypatch, tmp_path):
    corpora_path = tmp_path / "b372_corpora.json"
    results_path = tmp_path / "b372_results.json"
    corpora_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tc, "CORPORA_PATH", corpora_path)
    monkeypatch.setattr(tc, "RESULTS_PATH", results_path)
    monkeypatch.setattr(tc, "_build_tasks", lambda corpora: _fake_tasks())
    monkeypatch.setattr(tc, "_run_arm", lambda arm, prompt: (_ for _ in ()).throw(AssertionError("should not run")))

    tc.cmd_compare(yes=False, arms=list(tc.ARMS_ALL))
    assert not results_path.is_file()
