import json, os, copy
from dataclasses import replace
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import model as m
from model import Params

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT, exist_ok=True)
COL = {"AWS (managed cache/DB)": "#E8710A", "GCP (managed cache/DB)": "#4285F4",
       "GCP (self-hosted cache/DB, Meesho-style)": "#0B8043",
       "Hybrid (GCP edge + own cache/DB)": "#9334E6", "On-premises (all, lower bound)": "#B3261E"}
ONP = "On-premises (all, lower bound)"
HYB = "Hybrid (GCP edge + own cache/DB)"
GCPM = "GCP (managed cache/DB)"
R = {}
base = Params()

# base case
R["base"] = {}
for commit in ("on_demand", "1y", "3y"):
    ev = m.evaluate(base, commit)
    R["base"][commit] = ev
ev = R["base"]["3y"]
R["egress_tb_month"] = ev["egress_tb_month"]
R["onprem_detail"] = ev["onprem_detail"]


gcp_inr_cr_year = ev["scenarios"][GCPM]["monthly_usd"] * 12 * base.fx / 1e7
R["calibration"] = {"gcp_modelled_inr_cr_per_year": gcp_inr_cr_year, "meesho_reported_server_software_inr_cr_FY25": 620,
                    "cdn_share_of_modelled_bill": (ev["scenarios"][GCPM]["items"]["CDN egress"] + ev["scenarios"][GCPM]["items"]["CDN requests"]) / ev["scenarios"][GCPM]["monthly_usd"]}

# chart 1: monthly cost stacked by group
GROUPS = {"CDN egress + requests + fill": ("CDN egress", "CDN requests", "Cache fill (origin)"),
          "Object storage": ("Object storage", "Object storage hardware"),
          "App compute": ("App compute",),
          "Cache + database": ("Cache tier", "Database compute", "Database SSD", "Extra ops staff (self-hosting)")}
def group_of(name):
    for g, keys in GROUPS.items():
        if any(name == k or name.endswith(k) for k in keys):
            return g
    if name.startswith("Own data tier") or name in ("Colo rack rent", "Colo power", "Hardware maintenance", "IT staff") or "transit" in name.lower():
        if "transit" in name.lower(): return "IP transit (own)"
        return "Own facilities (rack, power, staff)"
    return "Other"
sc = m.scenarios(base, "3y")
order = list(sc)
cats = ["CDN egress + requests + fill", "Object storage", "App compute", "Cache + database",
        "IP transit (own)", "Own facilities (rack, power, staff)"]
agg = {n: {c: 0.0 for c in cats} for n in order}
for n in order:
    for k, v in sc[n]["items"].items():
        g = group_of(k)
        if k.startswith("Own data tier: IP transit"): g = "IP transit (own)"
        agg[n][g] = agg[n].get(g, 0) + v
R["grouped_monthly_usd"] = agg
fig, ax = plt.subplots(figsize=(10, 5))
colors = ["#4285F4", "#34A853", "#FBBC04", "#EA4335", "#9334E6", "#80868B"]
left = np.zeros(len(order))
SHORT = {"AWS (managed cache/DB)": "AWS\nmanaged", "GCP (managed cache/DB)": "GCP\nmanaged", "GCP (self-hosted cache/DB, Meesho-style)": "GCP\nself-hosted\ncache/DB", "Hybrid (GCP edge + own cache/DB)": "Hybrid\nGCP edge + own\ncache/DB", "On-premises (all, lower bound)": "On-premises\n(lower bound)"}
labels = [SHORT[n] for n in order]
for c, col in zip(cats, colors):
    vals = np.array([agg[n][c] / 1e3 for n in order])
    ax.bar(range(len(order)), vals, bottom=left, label=c, color=col)
    left += vals
for i, n in enumerate(order):
    ax.text(i, left[i] + 8, f"${left[i]:,.0f}k", ha="center", fontsize=9, fontweight="bold")
ax.set_xticks(range(len(order))); ax.set_xticklabels(labels, fontsize=9)
ax.set_ylabel("Monthly cost (USD thousands)"); ax.set_title("Monthly cost by scenario, base workload, 3-year commitment")
ax.set_ylim(0, left.max() * 1.12)
ax.legend(fontsize=8, loc="center left", bbox_to_anchor=(1.01, 0.5)); ax.grid(axis="y", alpha=.3)
plt.savefig(f"{OUT}/fig1_monthly_cost.png", dpi=170, bbox_inches="tight"); plt.close()

# chart 2: cumulative cost and break even
H = 120
fig, ax = plt.subplots(figsize=(9, 5))
t = np.arange(H + 1)
for n in order:
    ax.plot(t, m.cumulative(sc[n], H) / 1e6, label=n, color=COL[n], lw=2.2 if "On-prem" in n or "GCP (managed" in n else 1.6)
be = ev["breakeven_months_vs_onprem"][GCPM]
if be is not None:
    ax.axvline(be, color="k", ls="--", lw=1); ax.annotate(f"GCP vs on-prem\nbreak-even: month {be}", (be, m.cumulative(sc[GCPM], H)[be] / 1e6), (be + 6, 8), arrowprops=dict(arrowstyle="->"), fontsize=9)
ax.axvline(60, color="grey", ls=":", lw=1); ax.text(61, 1, "hardware refresh", fontsize=8, color="grey")
ax.set_xlabel("Months"); ax.set_ylabel("Cumulative cost (USD millions)"); ax.set_title("Cumulative cost and break-even (3-year commitment, base workload)")
ax.legend(fontsize=8); ax.grid(alpha=.3); plt.tight_layout(); plt.savefig(f"{OUT}/fig2_breakeven.png", dpi=170); plt.close()

# 3. sensitivity on 5 year TCO gap
def gap(p, commit="3y"):
    s = m.scenarios(p, commit)
    return (m.tco(s[GCPM]) - m.tco(s[ONP])) / 1e6
def gap_h(p, commit="3y"):
    s = m.scenarios(p, commit)
    return (m.tco(s[GCPM]) - m.tco(s[HYB])) / 1e6
base_gap, base_gap_h = gap(base), gap_h(base)
tests = [("Average object size (20 / 60 KB)", dict(avg_object_kb=20), dict(avg_object_kb=60)),
         ("Peak-to-average ratio (2 / 4)", dict(peak_ratio=2), dict(peak_ratio=4)),
         ("Negotiated CDN egress discount (0.4 / 0)", dict(egress_discount=0.4), dict(egress_discount=0.0)),
         ("Baseline app vCPU (500 / 2000)", dict(baseline_vcpu=500), dict(baseline_vcpu=2000)),
         ("Commitment coverage (0.4 / 0.9)", dict(commit_share=0.4), dict(commit_share=0.9)),
         ("Migration cost (1.0M / 0 USD)", dict(migration_usd=1_000_000), dict(migration_usd=0)),
         ("Number of on-prem sites (3 / 1)", dict(onprem_sites=3), dict(onprem_sites=1)),
         ("Peak hours share (2% / 10%)", dict(peak_time_fraction=0.02), dict(peak_time_fraction=0.10)),
         ("Cache hit ratio (0.97 / 0.995)", dict(cache_hit=0.97), dict(cache_hit=0.995))]
def with_price(key, val):
    old = copy.deepcopy(m.PRICES["onprem"][key])
    m.PRICES["onprem"][key]["base"] = val
    return old
def _pt(label, key, unit):
    d = m.PRICES["onprem"][key]
    return (f"{label} ({d['high']:,} / {d['low']:,} {unit})", key, d["high"], d["low"])
price_tests = [_pt("Server price", "server_usd", "USD"),
               _pt("Colo power", "colo_power_inr_kw_month", "INR per kW"),
               _pt("Staff cost", "staff_loaded_inr_month", "INR per month")]
rows = []
for label, lo, hi in tests:
    rows.append((label, gap(replace(base, **lo)) - base_gap, gap(replace(base, **hi)) - base_gap))
for label, key, a, b in price_tests:
    old = with_price(key, a); ga = gap(base) - base_gap
    m.PRICES["onprem"][key] = copy.deepcopy(old); with_price(key, b); gb = gap(base) - base_gap
    m.PRICES["onprem"][key] = old
    rows.append((label, ga, gb))
rows.sort(key=lambda r: -(max(abs(r[1]), abs(r[2]))))
R["sensitivity"] = {"base_gap_musd_gcp_minus_onprem_5y": base_gap, "rows": [dict(label=r[0], delta_a=r[1], delta_b=r[2]) for r in rows]}
fig, ax = plt.subplots(figsize=(9.5, 5.5))
for i, (label, a, b) in enumerate(rows[::-1]):
    ax.barh(i, a, color="#B3261E" if a < 0 else "#4285F4"); ax.barh(i, b, color="#B3261E" if b < 0 else "#4285F4")
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows[::-1]], fontsize=8)
ax.axvline(0, color="k", lw=1)
ax.set_xlabel(f"Change in 5-year TCO gap (GCP minus on-prem), USD millions. Base gap = {base_gap:,.1f}M")
ax.set_title("Sensitivity: what moves the cloud vs on-prem gap (positive = cloud dearer)")
ax.grid(axis="x", alpha=.3); plt.tight_layout(); plt.savefig(f"{OUT}/fig3_sensitivity.png", dpi=170); plt.close()

# 4. scaling
ks = [0.1, 0.25, 0.5, 1.0, 1.5, 2.0]
scal = []
for k in ks:
    p = base.scaled(k); s = m.scenarios(p, "3y")
    scal.append(dict(k=k, gcp_monthly=s[GCPM]["monthly"], aws_monthly=s["AWS (managed cache/DB)"]["monthly"],
                     onprem_monthly=s[ONP]["monthly"], hybrid_monthly=s[HYB]["monthly"],
                     be_onprem=m.breakeven_month(s[GCPM], s[ONP], 240), be_hybrid=m.breakeven_month(s[GCPM], s[HYB], 240),
                     tco5_ratio_onprem_vs_gcp=m.tco(s[ONP]) / m.tco(s[GCPM]),
                     servers=m.onprem_costs(p)["servers"]))
R["scaling"] = scal
fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
ax[0].plot(ks, [x["gcp_monthly"] / 1e3 for x in scal], "o-", color=COL[GCPM], label="GCP managed")
ax[0].plot(ks, [x["aws_monthly"] / 1e3 for x in scal], "o-", color=COL["AWS (managed cache/DB)"], label="AWS managed")
ax[0].plot(ks, [x["hybrid_monthly"] / 1e3 for x in scal], "o-", color=COL[HYB], label="Hybrid")
ax[0].plot(ks, [x["onprem_monthly"] / 1e3 for x in scal], "o-", color=COL[ONP], label="On-prem (running cost only)")
ax[0].set_xlabel("Workload scale (1.0 = base case)"); ax[0].set_ylabel("Monthly cost (USD thousands)"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
ax[0].set_title("Monthly cost vs workload size")
ax[1].plot(ks, [x["be_onprem"] if x["be_onprem"] is not None else np.nan for x in scal], "o-", color=COL[ONP], label="vs on-prem (all)")
ax[1].plot(ks, [x["be_hybrid"] if x["be_hybrid"] is not None else np.nan for x in scal], "o-", color=COL[HYB], label="vs hybrid")
ax[1].set_xlabel("Workload scale"); ax[1].set_ylabel("Break-even month (GCP 3y commit)"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
ax[1].set_title("Break-even month vs workload size")
plt.tight_layout(); plt.savefig(f"{OUT}/fig4_scaling.png", dpi=170); plt.close()

# 5. heatmaps
pr = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0]; kb = [5, 10, 20, 40, 60, 80]
grid = np.full((len(pr), len(kb)), np.nan)
for i, a_ in enumerate(pr):
    for j, b_ in enumerate(kb):
        p = replace(base, peak_ratio=a_, avg_object_kb=b_); s_ = m.scenarios(p, "3y")
        v = m.breakeven_month(s_[GCPM], s_[ONP], 240); grid[i, j] = v if v is not None else np.nan
tr = [30, 60, 100, 150, 250, 300, 400, 600, 750]; dc = [0.0, 0.2, 0.4, 0.6]
grid2 = np.full((len(dc), len(tr)), np.nan)
def with_transit(v):
    old_ = m.PRICES["onprem"]["transit_inr_per_mbps_month"]["base"]; m.PRICES["onprem"]["transit_inr_per_mbps_month"]["base"] = v; return old_
for i, d in enumerate(dc):
    for j, t_ in enumerate(tr):
        old_ = with_transit(t_); p = replace(base, egress_discount=d); s_ = m.scenarios(p, "3y")
        v = m.breakeven_month(s_[GCPM], s_[ONP], 240); grid2[i, j] = v if v is not None else np.nan
        m.PRICES["onprem"]["transit_inr_per_mbps_month"]["base"] = old_
R["heatmap"] = dict(peak_ratio=pr, object_kb=kb, be_vs_onprem=np.where(np.isnan(grid), None, grid).tolist(),
                    transit=tr, discount=dc, be_transit_discount=np.where(np.isnan(grid2), None, grid2).tolist())
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
for ax, g, xl, yl, xt, yt, ttl in ((axs[0], grid, "Average object size (KB)", "Peak-to-average ratio", kb, pr, "Peak ratio x object size"),
                                    (axs[1], grid2, "Own IP transit price (INR per Mbps per month)", "Negotiated CDN egress discount", tr, dc, "Transit price x egress discount")):
    im = ax.imshow(np.ma.masked_invalid(g), cmap="YlOrRd", aspect="auto", vmin=0, vmax=120)
    ax.set_xticks(range(len(xt))); ax.set_xticklabels(xt); ax.set_yticks(range(len(yt))); ax.set_yticklabels(yt)
    ax.set_xlabel(xl); ax.set_ylabel(yl); ax.set_title(f"Break-even month, GCP vs on-prem: {ttl}", fontsize=9)
    for i in range(len(yt)):
        for j in range(len(xt)):
            ax.text(j, i, "never" if np.isnan(g[i, j]) else f"{int(g[i,j])}", ha="center", va="center", fontsize=8)
plt.tight_layout(); plt.savefig(f"{OUT}/fig5_heatmap.png", dpi=170); plt.close()

# 5b. parity transit price
def run_gap(tprice, disc, commit="3y", prov=GCPM):
    old_ = with_transit(tprice); p = replace(base, egress_discount=disc); s_ = m.scenarios(p, commit)
    g_ = s_[prov]["monthly"] - s_[ONP]["monthly"]; m.PRICES["onprem"]["transit_inr_per_mbps_month"]["base"] = old_; return g_
parity = {}
for d in (0.0, 0.2, 0.4, 0.6):
    g0, g1 = run_gap(0, d), run_gap(1000, d)
    parity[str(d)] = -g0 * 1000 / (g1 - g0)
R["parity_transit_inr_per_mbps"] = parity
fig, ax = plt.subplots(figsize=(8, 4.2))
xs = np.linspace(20, 900, 60)
for d, colr in zip((0.0, 0.2, 0.4, 0.6), ("#B3261E", "#E8710A", "#34A853", "#4285F4")):
    ax.plot(xs, [run_gap(x, d) / 1e3 for x in xs], label=f"CDN egress discount {int(d*100)}%", color=colr)
ax.axhline(0, color="k", lw=1); ax.set_xlabel("Own IP transit price (INR per Mbps per month)")
ax.set_ylabel("GCP monthly minus on-prem monthly (USD thousands)")
ax.set_title("Running-cost gap vs transit price (positive = cloud dearer)", fontsize=10); ax.legend(fontsize=8); ax.grid(alpha=.3)
plt.tight_layout(); plt.savefig(f"{OUT}/fig6_transit_parity.png", dpi=170); plt.close()

# 6. on prem low / base / high band
band = {}
for case in ("low", "base", "high"):
    p = replace(base, onprem_case=case); s = m.scenarios(p, "3y")
    band[case] = dict(onprem_monthly=s[ONP]["monthly"], onprem_capex=s[ONP]["capex"], tco5=m.tco(s[ONP]),
                      be_gcp=m.breakeven_month(s[GCPM], s[ONP], 240), be_aws=m.breakeven_month(s["AWS (managed cache/DB)"], s[ONP], 240),
                      hybrid_monthly=s[HYB]["monthly"], be_hybrid=m.breakeven_month(s[GCPM], s[HYB], 240))
R["onprem_band"] = band

# 7. provider comparison details
R["provider_gap"] = {c: dict(aws=R["base"][c]["scenarios"]["AWS (managed cache/DB)"]["monthly_usd"],
                             gcp=R["base"][c]["scenarios"][GCPM]["monthly_usd"]) for c in R["base"]}
old = copy.deepcopy(m.PRICES["aws"]["cdn_egress_tiers_india"]["tiers"])
m.PRICES["aws"]["cdn_egress_tiers_india"]["tiers"] = [[u, pr_ if u <= 150 else pr_ * 0.75] for u, pr_ in old]
s = m.scenarios(base, "3y"); R["aws_cheap_tail"] = dict(aws=s["AWS (managed cache/DB)"]["monthly"], gcp=s[GCPM]["monthly"], note="AWS tiers above 150 TB set 25% lower")
m.PRICES["aws"]["cdn_egress_tiers_india"]["tiers"] = old

json.dump(R, open(f"{OUT}/results.json", "w"), indent=1, default=lambda o: None if o is None else float(o))
print("done")