from __future__ import annotations
import json, os
from dataclasses import dataclass, replace

HERE = os.path.dirname(os.path.abspath(__file__))
HOURS = 730.0  # hours per month
DAYS = 30.0


def load_prices(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, "prices.json")) as f:
        return json.load(f)


PRICES = load_prices()


@dataclass(frozen=True)
class Params:
    storage_tb: float = 1000.0  # image store, 1 PB (Google Cloud CDN post)
    cdn_requests_per_day: float = 10e9  # Google Cloud CDN post
    avg_object_kb: float = 40.0
    cache_hit: float = 0.99  # Google Cloud CDN post
    baseline_vcpu: float = 1000.0
    peak_ratio: float = 3.0  # sales at 3x normal peak
    peak_time_fraction: float = 0.05
    cache_ram_gb: float = 4096.0
    db_vcpu: float = 400.0
    db_ssd_tb: float = 200.0
    commit_share: float = 0.7  # share of baseline vCPU covered by 1y/3y commitment
    egress_discount: float = 0.0

    selfhost_staff: int = 6  # extra engineers to self run cache/DB on cloud VMs
    fx: float = PRICES["fx_inr_per_usd"]["value"]
    horizon_months: int = 120

    def scaled(self, k: float) -> "Params":
        #  Scale the whole workload by factor k (used by the scaling experiment)
        return replace(
            self,
            storage_tb=self.storage_tb * k,
            cdn_requests_per_day=self.cdn_requests_per_day * k,
            baseline_vcpu=self.baseline_vcpu * k,
            cache_ram_gb=self.cache_ram_gb * k,
            db_vcpu=self.db_vcpu * k,
            db_ssd_tb=self.db_ssd_tb * k,
        )


# Monthly CDN egress in TB
def egress_tb(p: Params) -> float:
    return p.cdn_requests_per_day * DAYS * p.avg_object_kb * 1e3 / 1e12


# Tiered cost calculation
def tiered_cost(tb: float, tiers: list, discount: float = 0.0) -> float:
    cost, left = 0.0, tb
    for width, price in tiers:
        use = min(left, width)
        cost += use * 1000.0 * price
        left -= use
        if left <= 0:
            break
    return cost * (1 - discount)


# VM cost calculation
def vm_cost(
    vcpu: float,
    rates: dict,
    commit: str,
    share: float,
    peak_scale: float = 1.0,
    peak_frac: float = 0.0,
) -> float:
    od = rates["on_demand"]["value"]
    total_vcpu_hours = vcpu * HOURS * ((1 - peak_frac) + peak_scale * peak_frac)
    if commit == "on_demand":
        return total_vcpu_hours * od
    r = rates["commit_1y" if commit == "1y" else "commit_3y"]["value"]
    committed_hours = min(vcpu * share * HOURS, total_vcpu_hours)
    return committed_hours * r + (total_vcpu_hours - committed_hours) * od


# Calculate cloud costs for a given provider and parameters
def cloud_costs(
    p: Params, provider: str, commit: str = "on_demand", data_tier: str = "managed"
) -> dict:
    pr = PRICES[provider]
    sh = PRICES["shared"]
    eg = egress_tb(p)
    items = {}
    items["CDN egress"] = tiered_cost(
        eg, pr["cdn_egress_tiers_india"]["tiers"], p.egress_discount
    )
    items["CDN requests"] = (
        p.cdn_requests_per_day * DAYS / 1e4 * pr["cdn_request_per_10k"]["value"]
    )
    items["Cache fill (origin)"] = (
        eg * 1000 * (1 - p.cache_hit) * pr["cdn_origin_fill_gb"]["value"]
    )
    items["Object storage"] = (
        p.storage_tb * 1000 * pr["object_storage_gb_month"]["value"]
    )
    items["App compute"] = vm_cost(
        p.baseline_vcpu,
        pr["vcpu_hour"],
        commit,
        p.commit_share,
        p.peak_ratio,
        p.peak_time_fraction,
    )
    cache_vcpu = p.cache_ram_gb / sh["ram_gb_per_vcpu"]["value"]
    cache = vm_cost(cache_vcpu, pr["vcpu_hour"], commit, p.commit_share)
    db = vm_cost(p.db_vcpu, pr["vcpu_hour"], commit, p.commit_share)
    if data_tier == "managed":
        cache *= pr["managed_multiplier_cache"]["value"]
        db *= pr["managed_multiplier_db"]["value"]
    items["Cache tier"] = cache
    items["Database compute"] = db
    items["Database SSD"] = p.db_ssd_tb * 1000 * sh["block_ssd_gb_month"]["value"]
    if data_tier == "self":
        items["Extra ops staff (self-hosting)"] = (
            p.selfhost_staff * sh["selfhost_engineer_inr_month"]["value"] / p.fx
        )
    return items
