import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import model as m
from model import Params


def test_tiered_cost_simple():
    tiers = [[10, 0.10], [1e9, 0.05]]
    assert abs(m.tiered_cost(15, tiers) - 1250.0) < 1e-6  # 10 TB at 0.10 + 5 TB at 0.05
    assert abs(m.tiered_cost(15, tiers, 0.2) - 1250.0 * 0.8) < 1e-6


def test_egress_volume():
    assert abs(m.egress_tb(Params()) - 12000.0) < 1e-6  # 10bn req/day * 30 * 40 KB


def test_commitment_is_cheaper():
    p = Params()
    od = sum(m.cloud_costs(p, "gcp", "on_demand").values())
    y1 = sum(m.cloud_costs(p, "gcp", "1y").values())
    y3 = sum(m.cloud_costs(p, "gcp", "3y").values())
    assert y3 < y1 < od


def test_managed_multiplier():
    p = Params()
    man = m.cloud_costs(p, "gcp", "3y", "managed")
    slf = m.cloud_costs(p, "gcp", "3y", "self")
    assert abs(slf["Cache tier"] * 2.5 - man["Cache tier"]) < 1e-6


def test_scaling_roughly_linear():
    p = Params()
    a = sum(m.cloud_costs(p, "gcp", "3y").values())
    b = sum(m.cloud_costs(p.scaled(2), "gcp", "3y").values())
    assert 1.5 < b / a < 2.5
