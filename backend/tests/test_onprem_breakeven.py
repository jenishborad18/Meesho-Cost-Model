import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import model as m
from model import Params


def test_cumulative_starts_at_capex_and_grows():
    sc = m.scenarios(Params())
    on = sc["On-premises (all, lower bound)"]
    cum = m.cumulative(on, 120)
    assert abs(cum[0] - (on["capex"] + on["oneoff"])) < 1e-6
    assert np.all(np.diff(cum) > 0)
    assert cum[60] - cum[59] > on["monthly"] + 0.9 * on["hw_capex"]   # refresh at month 60 i.e 5 years


def test_breakeven_moves_with_cloud_price():
    sc = m.scenarios(Params())
    on = sc["On-premises (all, lower bound)"]
    cheap = dict(sc["GCP (managed cache/DB)"]); cheap["monthly"] = on["monthly"] * 1.05
    dear = dict(sc["GCP (managed cache/DB)"]); dear["monthly"] = on["monthly"] * 2.0
    b_cheap, b_dear = m.breakeven_month(cheap, on, 240), m.breakeven_month(dear, on, 240)
    assert b_dear is not None and (b_cheap is None or b_cheap > b_dear)


def test_never_breaks_even_when_cloud_cheaper():
    sc = m.scenarios(Params())
    on = sc["On-premises (all, lower bound)"]
    cloud = dict(sc["GCP (managed cache/DB)"]); cloud["monthly"] = on["monthly"] * 0.5
    assert m.breakeven_month(cloud, on, 120) is None


def test_two_sites_default():
    assert m.onprem_costs(Params())["capex_usd"] > 1.9 * m.onprem_costs(Params(onprem_sites=1))["capex_usd"]
