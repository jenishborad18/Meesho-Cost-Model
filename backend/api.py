"""
Endpoints
  GET  /health     liveness check
  GET  /schema     input fields (label, range, default, unit) so the front end builds its form from one source of truth
  GET  /prices     price table with status and source
  POST /evaluate   run the model, returns scenarios, line items, cumulative cost series and break even months
  /                the static front end (../frontend)
"""
import os
from typing import Literal, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import Field, create_model

import model as m

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "..", "frontend")
D = m.Params()

# name, label, group, min, max, step, unit, help, display_scale (UI value x scale = model value), type
FIELDS = [
    ("storage_tb", "Image storage", "Workload", 10, 20000, 10, "TB", "Product images held in object storage. Meesho: 1+ PB.", 1, float),
    ("cdn_requests_per_day", "CDN requests per day", "Workload", 0.01, 100, 0.5, "billion", "Requests reaching the CDN. Meesho: about 10 billion a day.", 1e9, float),
    ("avg_object_kb", "Average object size", "Workload", 1, 200, 1, "KB", "Assumption. Sets monthly egress volume.", 1, float),
    ("cache_hit", "CDN cache hit ratio", "Workload", 0, 0.999, 0.001, "ratio", "Share of requests served from the CDN edge. Meesho: above 0.99.", 1, float),
    ("baseline_vcpu", "Baseline app vCPU", "Workload", 10, 20000, 50, "vCPU", "Application servers at normal load.", 1, float),
    ("peak_ratio", "Peak-to-average ratio", "Workload", 1, 8, 0.5, "x", "Sale days reach about 3x normal load.", 1, float),
    ("peak_time_fraction", "Share of hours at peak", "Workload", 0, 0.5, 0.01, "ratio", "Assumption.", 1, float),
    ("cache_ram_gb", "Cache memory", "Workload", 16, 200000, 256, "GB", "RAM for the cache tier (Redis/Dragonfly).", 1, float),
    ("db_vcpu", "Database vCPU", "Workload", 1, 10000, 50, "vCPU", "Database compute.", 1, float),
    ("db_ssd_tb", "Database SSD", "Workload", 0, 5000, 10, "TB", "Database storage.", 1, float),
    ("commit_share", "Baseline covered by commitment", "Commercial terms", 0, 1, 0.05, "ratio", "Share of baseline vCPU under a 1y/3y commitment.", 1, float),
    ("egress_discount", "Negotiated CDN egress discount", "Commercial terms", 0, 0.8, 0.05, "ratio", "Discount off list price for large volume.", 1, float),
    ("onprem_sites", "On-prem sites", "On-premises", 1, 4, 1, "sites", "A DR copy is needed in production.", 1, int),
    ("migration_usd", "One-off migration cost", "On-premises", 0, 5000000, 50000, "USD", "Cost of moving off the cloud (assumption).", 1, float),
    ("selfhost_staff", "Extra engineers to self-host cache/DB", "On-premises", 0, 50, 1, "people", "Used by the self-hosted and hybrid scenarios.", 1, int),
    ("fx", "INR per USD", "Money and time", 60, 120, 0.5, "INR", "Not looked up; edit.", 1, float),
    ("horizon_months", "Horizon", "Money and time", 24, 240, 12, "months", "How far to project the cumulative cost.", 1, int),
]
SELECTS = [
    ("commit", "Cloud commitment", "Commercial terms", ["3y", "1y", "on_demand"], "3y"),
    ("onprem_case", "On-prem price case", "On-premises", ["base", "low", "high"], "base"),
]

_model_fields = {}
for name, _l, _g, lo, hi, _s, _u, _h, scale, typ in FIELDS:
    optional_typ = typ | None
    _model_fields[name] = (optional_typ, Field(None, ge=(1 if name == "cdn_requests_per_day" else lo * scale), le=hi * scale))
_model_fields["commit"] = (Literal["3y", "1y", "on_demand"], "3y")
_model_fields["onprem_case"] = (Optional[Literal["low", "base", "high"]], None)
Overrides = create_model("Overrides", **_model_fields)


app = FastAPI(title="Meesho cloud repatriation cost model", version="2.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/schema")
def schema():
    fields = [dict(name=n, label=l, group=g, min=lo, max=hi, step=st, unit=u, help=h, scale=sc,
                   default=(getattr(D, n) / sc), type="int" if t is int else "float")
              for n, l, g, lo, hi, st, u, h, sc, t in FIELDS]
    selects = [dict(name=n, label=l, group=g, options=o, default=d) for n, l, g, o, d in SELECTS]
    return {"fields": fields, "selects": selects}


@app.get("/prices")
def prices():
    meta = m.PRICES["_meta"]
    legend = meta.get("status_legend", {})
    note = meta.get("note") or "Status: " + " ".join(f"{k} = {v}." for k, v in legend.items())
    return {"retrieved": meta["retrieved"], "note": note, "rows": m.price_table()}


@app.post("/evaluate")
def evaluate(o: Overrides): # type: ignore
    data = o.model_dump()
    commit = data.pop("commit")
    kw = {k: v for k, v in data.items() if v is not None}
    p = m.Params(**kw)
    r = m.evaluate(p, commit, include_series=True)
    r["horizon_months"] = p.horizon_months
    r["fx"] = p.fx
    r["commit"] = commit
    return r


if os.path.isdir(FRONTEND):
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")