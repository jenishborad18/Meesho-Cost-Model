from __future__ import annotations
import json, math, os
from dataclasses import dataclass, replace
import numpy as np

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

    onprem_case: str = "base"  # low | base | high
    migration_usd: float = 250000.0  # cost of leaving the cloud
    onprem_sites: int = 2
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


# Resolve on premises pricing value for the selected cost case
def _o(key: str, case: str):
    d = PRICES["onprem"][key]
    return d[case] if case in d else d["value"]


# Calculate on premises capital and monthly operating costs
def onprem_costs(
    p: Params, include=("app", "cache", "db", "storage", "transit")
) -> dict:
    c = p.onprem_case
    head = _o("capacity_headroom", c)
    sv_vcpu, sv_kw = _o("server_vcpu", c), _o("server_kw", c)
    cache_vcpu = p.cache_ram_gb / PRICES["shared"]["ram_gb_per_vcpu"]["value"]
    vcpu_need = 0.0
    if "app" in include:
        vcpu_need += p.baseline_vcpu * p.peak_ratio * head
    if "cache" in include:
        vcpu_need += cache_vcpu * head
    if "db" in include:
        vcpu_need += p.db_vcpu * head
    servers = math.ceil(vcpu_need / sv_vcpu) if vcpu_need else 0
    hw = {"Servers": servers * _o("server_usd", c)}
    if "cache" in include:
        hw["Extra RAM (cache)"] = p.cache_ram_gb * head * _o("ram_usd_per_gb", c)
    if "db" in include:
        hw["NVMe (database)"] = p.db_ssd_tb * head * _o("nvme_usd_per_tb", c)
    raw_tb = 0.0
    if "storage" in include:
        raw_tb = p.storage_tb * _o("storage_overhead_factor", c) * head
        hw["Object storage hardware"] = raw_tb * _o("hdd_object_usd_per_raw_tb", c)
    hw["Network gear"] = sum(hw.values()) * _o("network_gear_pct_of_hw", c)
    sites = max(1, p.onprem_sites)
    hw = {k: v * sites for k, v in hw.items()}
    hw_total = sum(hw.values())
    kw = (servers * sv_kw + raw_tb * _o("storage_kw_per_raw_tb", c)) * sites
    racks = math.ceil(kw / _o("rack_kw_limit", c)) if kw else 0
    setup = racks * _o("setup_labour_inr_per_rack", c) / p.fx

    peak_gbps = 0.0
    transit = 0.0
    if "transit" in include:
        avg_gbps = egress_tb(p) * 1e12 * 8 / (DAYS * 86400) / 1e9
        peak_gbps = avg_gbps * p.peak_ratio
        transit = peak_gbps * 1000 * _o("transit_inr_per_mbps_month", c) / p.fx * sites
    staff_n = (
        max(
            _o("staff_min", c),
            math.ceil(servers / 100 * _o("staff_per_100_servers", c)),
        )
        if servers
        else 0
    )
    staff_n = math.ceil(staff_n * (1 + 0.5 * (sites - 1)))
    items = {
        "Colo rack rent": racks * _o("colo_rack_inr_month", c) / p.fx,
        "Colo power": kw * _o("colo_power_inr_kw_month", c) / p.fx,
        "IP transit (sized for peak)": transit,
        "Hardware maintenance": hw_total * _o("maintenance_pct_per_year", c) / 12,
        "IT staff": staff_n * _o("staff_loaded_inr_month", c) / p.fx,
    }
    return dict(
        capex_usd=hw_total + setup,
        hw_usd=hw_total,
        monthly_usd=sum(items.values()),
        items=items,
        hw_items=hw,
        servers=servers * sites,
        racks=racks,
        kw=kw,
        peak_gbps=peak_gbps,
        staff=staff_n,
    )


# Build the supported cloud, hybrid and on premises architecture scenarios
def scenarios(p: Params, commit: str = "3y") -> dict:
    out = {}
    for prov, label in (
        ("aws", "AWS (managed cache/DB)"),
        ("gcp", "GCP (managed cache/DB)"),
    ):
        it = cloud_costs(p, prov, commit, "managed")
        out[label] = dict(
            kind="cloud", monthly=sum(it.values()), capex=0.0, oneoff=0.0, items=it
        )
    it = cloud_costs(p, "gcp", commit, "self")
    out["GCP (self-hosted cache/DB, Meesho-style)"] = dict(
        kind="cloud", monthly=sum(it.values()), capex=0.0, oneoff=0.0, items=it
    )
    g = cloud_costs(p, "gcp", commit, "managed")
    edge = {
        k: g[k]
        for k in (
            "CDN egress",
            "CDN requests",
            "Cache fill (origin)",
            "Object storage",
            "App compute",
        )
    }
    dt = onprem_costs(p, include=("cache", "db"))
    items = dict(edge)
    items.update({"Own data tier: " + k: v for k, v in dt["items"].items()})
    out["Hybrid (GCP edge + own cache/DB)"] = dict(
        kind="onprem",
        monthly=sum(items.values()),
        capex=dt["capex_usd"],
        hw_capex=dt["hw_usd"],
        oneoff=0.5 * p.migration_usd,
        items=items,
    )
    op = onprem_costs(p)
    out["On-premises (all, lower bound)"] = dict(
        kind="onprem",
        monthly=op["monthly_usd"],
        capex=op["capex_usd"],
        hw_capex=op["hw_usd"],
        oneoff=p.migration_usd,
        items=op["items"],
        detail=op,
    )
    return out


# Calculate cumulative total cost over the requested number of months
def cumulative(s: dict, months: int, life_years: float = 5.0) -> np.ndarray:
    t = np.arange(months + 1, dtype=float)
    cum = s["monthly"] * t
    if s["kind"] == "onprem":
        life = int(life_years * 12)
        cum = cum + s["capex"] + s["oneoff"]
        # hardware refresh every `life` months
        for k in range(1, months // life + 1):
            cum = cum + np.where(t >= k * life, s.get("hw_capex", s["capex"]), 0.0)
    return cum


# Find the first month when the on premises architecture is cheaper than the comparison
def breakeven_month(
    cloud: dict, onprem: dict, horizon: int = 120, life_years: float = 5.0
):
    c = cumulative(cloud, horizon)
    o = cumulative(onprem, horizon, life_years)
    idx = np.where(o <= c)[0]
    return int(idx[0]) if len(idx) else None


# Return the scenario's total cost at the end of the selected horizon
def tco(s: dict, months: int = 60, life_years: float = 5.0) -> float:
    return float(cumulative(s, months, life_years)[-1])


GROUPS = {
    "CDN (egress, requests, fill)": (
        "CDN egress",
        "CDN requests",
        "Cache fill (origin)",
    ),
    "Object storage": ("Object storage", "Object storage hardware"),
    "App compute": ("App compute",),
    "Cache and database": (
        "Cache tier",
        "Database compute",
        "Database SSD",
        "Extra ops staff (self-hosting)",
    ),
    "Own IP transit": ("IP transit (sized for peak)",),
    "Own facilities (rack, power, staff)": (
        "Colo rack rent",
        "Colo power",
        "Hardware maintenance",
        "IT staff",
    ),
}


# Collapse detailed line items into the chart cost groups used by the frontend
def group_items(items: dict) -> dict:
    out = {g: 0.0 for g in GROUPS}
    for name, v in items.items():
        base_name = (
            name.split(": ", 1)[1] if name.startswith("Own data tier: ") else name
        )
        for g, keys in GROUPS.items():
            if base_name in keys:
                out[g] += v
                break
        else:
            out.setdefault("Other", 0.0)
            out["Other"] += v
    return {g: v for g, v in out.items() if v}


# Flatten the price configuration into rows for the frontend price table
def price_table() -> list:
    rows = []

    def walk(prefix, node):
        if isinstance(node, dict):
            if "status" in node and (
                "value" in node or "tiers" in node or "low" in node
            ):
                val = node.get(
                    "value",
                    node.get(
                        "tiers",
                        f"low {node.get('low')} / base {node.get('base')} / high {node.get('high')}",
                    ),
                )
                rows.append(
                    dict(
                        item=prefix,
                        value=str(val),
                        status=node["status"],
                        source=node.get("source", node.get("note", "")),
                    )
                )
            else:
                for k, v in node.items():
                    if not k.startswith("_"):
                        walk(f"{prefix}.{k}" if prefix else k, v)

    walk("", PRICES)
    return rows


# Evaluate scenarios, breakeven points and monthly cost series for the parameters
def evaluate(p: Params, commit: str = "3y", include_series: bool = False) -> dict:
    sc = scenarios(p, commit)
    names = list(sc)
    res = {"egress_tb_month": egress_tb(p), "scenarios": {}}
    for n in names:
        res["scenarios"][n] = dict(
            monthly_usd=sc[n]["monthly"],
            monthly_inr_cr=sc[n]["monthly"] * p.fx / 1e7,
            capex_usd=sc[n]["capex"],
            tco5_usd=tco(sc[n], 60),
            tco10_usd=tco(sc[n], 120),
            items=sc[n]["items"],
            groups=group_items(sc[n]["items"]),
        )
        if include_series:
            res["scenarios"][n]["cumulative_usd"] = [
                round(float(x)) for x in cumulative(sc[n], p.horizon_months)
            ]
    onp = sc["On-premises (all, lower bound)"]
    res["breakeven_months_vs_onprem"] = {
        n: breakeven_month(sc[n], onp, p.horizon_months)
        for n in names
        if sc[n]["kind"] == "cloud"
    }
    hyb = sc["Hybrid (GCP edge + own cache/DB)"]
    res["breakeven_months_vs_hybrid"] = {
        n: breakeven_month(sc[n], hyb, p.horizon_months)
        for n in names
        if sc[n]["kind"] == "cloud"
    }
    res["onprem_detail"] = {k: v for k, v in onp["detail"].items() if k != "items"}
    return res


if __name__ == "__main__":
    r = evaluate(Params())
    print(
        json.dumps(
            {
                k: (
                    v
                    if k != "scenarios"
                    else {n: round(s["monthly_usd"]) for n, s in v.items()}
                )
                for k, v in r.items()
            },
            indent=1,
            default=str,
        )
    )
