"""Deterministic ICP filter (Phase 6): employee band + criteria, unknown != reject."""

import pytest

from app.services.icp_filter_service import evaluate_company_icp, icp_filter_active


class _RS:
    def __init__(self, lo=100, hi=3000, crit=None):
        self.icp_min_employees = lo
        self.icp_max_employees = hi
        self.icp_criteria_json = crit


def test_size_band():
    rs = _RS(100, 3000)
    assert evaluate_company_icp({"employee_count": 40}, rs)["verdict"] == "reject"
    assert evaluate_company_icp({"employee_count": 5000}, rs)["verdict"] == "reject"
    assert evaluate_company_icp({"employee_count": 800}, rs)["verdict"] == "pass"


def test_unknown_is_not_reject():
    rs = _RS(100, 3000)
    assert evaluate_company_icp({}, rs)["verdict"] == "unknown"
    assert evaluate_company_icp(None, rs)["verdict"] == "unknown"
    assert evaluate_company_icp({"okved": "62.01"}, rs)["verdict"] == "unknown"  # no size, no size-criteria checkable


def test_open_band_side():
    rs = _RS(100, None)  # only a minimum
    assert evaluate_company_icp({"employee_count": 50}, rs)["verdict"] == "reject"
    assert evaluate_company_icp({"employee_count": 99999}, rs)["verdict"] == "pass"


def test_okved_include_exclude():
    rs = _RS(None, None, {"okved_exclude": ["84"]})  # exclude public administration
    assert evaluate_company_icp({"okveds": ["84.11"]}, rs)["verdict"] == "reject"
    rs2 = _RS(None, None, {"okved_include": ["47", "10"]})  # retail / food
    assert evaluate_company_icp({"okved": "47.11"}, rs2)["verdict"] == "pass"
    assert evaluate_company_icp({"okved": "62.01"}, rs2)["verdict"] == "reject"


def test_region_and_revenue():
    rs = _RS(None, None, {"regions": ["Москва", "Московская"]})
    assert evaluate_company_icp({"region": "г Москва"}, rs)["verdict"] == "pass"
    assert evaluate_company_icp({"region": "Республика Татарстан"}, rs)["verdict"] == "reject"
    rs2 = _RS(None, None, {"revenue_min": 100_000_000})
    assert evaluate_company_icp({"revenue": 50_000_000}, rs2)["verdict"] == "reject"
    assert evaluate_company_icp({"revenue": 500_000_000}, rs2)["verdict"] == "pass"


def test_icp_filter_active():
    assert icp_filter_active(_RS(100, 3000)) is True
    assert icp_filter_active(_RS(None, None, {"regions": ["Москва"]})) is True
    assert icp_filter_active(_RS(None, None, None)) is False
    assert icp_filter_active(None) is False
