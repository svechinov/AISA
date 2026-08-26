"""Geo/size filters derived from RunSetup for Apollo org search (B-002): pure function, no network/DB."""

import pytest

from app.services.apollo_service import apollo_org_filters_from_run_setup, search_organizations_json


class _RS:
    def __init__(self, lo=None, hi=None, crit=None):
        self.icp_min_employees = lo
        self.icp_max_employees = hi
        self.icp_criteria_json = crit


_UP_TO_100 = ["1,10", "11,20", "21,50", "51,100"]


def test_both_bounds():
    rs = _RS(10, 500, {"regions": ["Cyprus"]})
    out = apollo_org_filters_from_run_setup(rs)
    assert out == {"locations": ["Cyprus"], "num_employees_ranges": ["10,500"]}


def test_only_lo():
    rs = _RS(10, None)
    out = apollo_org_filters_from_run_setup(rs)
    assert out["num_employees_ranges"] == ["10,100000"]


def test_only_hi():
    rs = _RS(None, 500)
    out = apollo_org_filters_from_run_setup(rs)
    assert out["num_employees_ranges"] == ["1,500"]


def test_neither_bound_falls_back_to_up_to_100():
    rs = _RS(None, None)
    out = apollo_org_filters_from_run_setup(rs)
    assert out["num_employees_ranges"] == _UP_TO_100
    assert out["locations"] == []


def test_lo_greater_than_hi_is_swapped_not_raised():
    rs = _RS(500, 10)
    out = apollo_org_filters_from_run_setup(rs)
    assert out["num_employees_ranges"] == ["10,500"]


def test_garbage_bounds_treated_as_unset():
    rs = _RS("ten", -5)
    out = apollo_org_filters_from_run_setup(rs)
    assert out["num_employees_ranges"] == _UP_TO_100
    rs2 = _RS(True, None)  # bool must not pass as int
    out2 = apollo_org_filters_from_run_setup(rs2)
    assert out2["num_employees_ranges"] == _UP_TO_100


def test_regions_blank_and_duplicates():
    rs = _RS(None, None, {"regions": ["Cyprus", " Cyprus ", "", "  ", "Malta", 5, None]})
    out = apollo_org_filters_from_run_setup(rs)
    assert out["locations"] == ["Cyprus", "Malta"]


def test_regions_missing_or_wrong_shape():
    assert apollo_org_filters_from_run_setup(_RS(None, None, None))["locations"] == []
    assert apollo_org_filters_from_run_setup(_RS(None, None, "Cyprus"))["locations"] == []
    assert apollo_org_filters_from_run_setup(_RS(None, None, ["Cyprus"]))["locations"] == []
    assert apollo_org_filters_from_run_setup(_RS(None, None, {}))["locations"] == []
    assert apollo_org_filters_from_run_setup(_RS(None, None, {"regions": "Cyprus"}))["locations"] == []
    assert apollo_org_filters_from_run_setup(_RS(None, None, {"regions": None}))["locations"] == []


def test_regions_limit_20():
    rs = _RS(None, None, {"regions": [f"Region{i}" for i in range(30)]})
    out = apollo_org_filters_from_run_setup(rs)
    assert len(out["locations"]) == 20
    assert out["locations"][0] == "Region0"


def test_run_setup_none():
    out = apollo_org_filters_from_run_setup(None)
    assert out == {"locations": [], "num_employees_ranges": _UP_TO_100}


def test_search_organizations_json_without_locations_omits_key(monkeypatch):
    captured = {}

    def _fake_post(path, *, json_body):
        captured["path"] = path
        captured["body"] = json_body
        return {}

    monkeypatch.setattr("app.services.apollo_service._apollo_post_json", _fake_post)
    search_organizations_json(["gamedev"], page=1, per_page=25)
    assert "organization_locations" not in captured["body"]
    assert captured["body"]["organization_num_employees_ranges"] == _UP_TO_100


def test_search_organizations_json_with_locations_sets_key(monkeypatch):
    captured = {}

    def _fake_post(path, *, json_body):
        captured["body"] = json_body
        return {}

    monkeypatch.setattr("app.services.apollo_service._apollo_post_json", _fake_post)
    search_organizations_json(
        ["gamedev"],
        page=1,
        per_page=25,
        locations=["Cyprus"],
        num_employees_ranges=["10,500"],
    )
    assert captured["body"]["organization_locations"] == ["Cyprus"]
    assert captured["body"]["organization_num_employees_ranges"] == ["10,500"]
