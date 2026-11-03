import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import warnings; warnings.filterwarnings("ignore")
from fastapi.testclient import TestClient
import api

c = TestClient(api.app)


def test_health():
    assert c.get("/health").json() == {"status": "ok"}


def test_schema_lists_all_inputs_with_defaults():
    s = c.get("/schema").json()
    names = {f["name"] for f in s["fields"]}
    assert {"storage_tb", "cdn_requests_per_day", "peak_ratio", "horizon_months"} <= names
    assert {x["name"] for x in s["selects"]} == {"commit", "onprem_case"}
    req = next(f for f in s["fields"] if f["name"] == "cdn_requests_per_day")
    assert req["scale"] == 1e9 and abs(req["default"] - 10.0) < 1e-9     # shown in billions


def test_prices_have_status_and_source():
    p = c.get("/prices").json()
    assert len(p["rows"]) > 30
    assert all(r["status"] for r in p["rows"])
    assert any(r["status"] == "ASSUMPTION" for r in p["rows"])
    assert p["note"] and all(r["source"] for r in p["rows"])


def test_evaluate_defaults_match_model():
    import model as m
    r = c.post("/evaluate", json={}).json()
    direct = m.evaluate(m.Params(), "3y")
    assert abs(r["egress_tb_month"] - 12000) < 1e-6
    for name, s in direct["scenarios"].items():
        assert abs(r["scenarios"][name]["monthly_usd"] - s["monthly_usd"]) < 1.0
    assert r["breakeven_months_vs_onprem"] == direct["breakeven_months_vs_onprem"]
    gcp = r["scenarios"]["GCP (managed cache/DB)"]
    assert len(gcp["cumulative_usd"]) == r["horizon_months"] + 1


def test_evaluate_override_changes_result():
    a = c.post("/evaluate", json={"avg_object_kb": 40}).json()
    b = c.post("/evaluate", json={"avg_object_kb": 20}).json()
    assert abs(b["egress_tb_month"] - a["egress_tb_month"] / 2) < 1e-6


def test_validation_rejects_out_of_range_and_bad_enum():
    assert c.post("/evaluate", json={"cache_hit": 33}).status_code == 422
    assert c.post("/evaluate", json={"egress_discount": 22}).status_code == 422
    assert c.post("/evaluate", json={"onprem_case": "db"}).status_code == 422
    assert c.post("/evaluate", json={"commit": "5y"}).status_code == 422


def test_small_workload_is_accepted():
    r = c.post("/evaluate", json={"cdn_requests_per_day": 456, "cache_hit": 0.33, "storage_tb": 12, "baseline_vcpu": 11}).json()
    assert r["scenarios"]["GCP (managed cache/DB)"]["monthly_usd"] > 0