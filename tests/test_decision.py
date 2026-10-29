"""Shortlist ranking: TOPSIS, weight stability, budget plan; needs helpers."""
import numpy as np
import pandas as pd

from fi import decision as fd
from fi.needs import slot_side, years_ru


def table():
    return pd.DataFrame({
        "fit": [80, 60, 70], "gap": [0.3, 0.1, -0.2], "age": [24, 29, 22], "role_minutes": [3000, 1500, 2000],
        "value": [10e6, 4e6, 30e6],
    }, index=["a", "b", "c"])


def test_topsis_dominant_candidate_is_first_and_scores_in_unit_range():
    s = fd.topsis(table())
    assert s.idxmax() == "a"
    assert ((s >= 0) & (s <= 1)).all()


def test_topsis_cost_criterion_prefers_lower_values():
    t = pd.DataFrame({"fit": [50, 50], "gap": [0, 0], "age": [21, 30], "role_minutes": [2000, 2000]}, index=["young", "old"])
    assert fd.topsis(t).idxmax() == "young"


def test_topsis_weight_means_what_it_says_for_signed_criterion():
    # equal weights on fit and gap: a candidate best on one and worst on the other ties with the mirror one
    t = pd.DataFrame({"fit": [90, 50], "gap": [-0.3, 0.3]}, index=["x", "y"])
    s = fd.topsis(t, {"fit": (0.5, True), "gap": (0.5, True)})
    assert np.isclose(s["x"], s["y"])


def test_stability_is_a_share():
    r = fd.rank(table())
    st = fd.stability(r, n=200, top=1)
    assert ((st >= 0) & (st <= 1)).all() and np.isclose(st.sum(), 1.0)


def test_budget_plan_respects_budget():
    ranked = {"RB": fd.rank(table()), "ST": fd.rank(table().rename(index=lambda i: i + "2"))}
    plan = fd.budget_plan(ranked, budget=15e6)
    cost = sum(ranked[s].at[i, "value"] for s, i in plan)
    assert cost <= 15e6 and len(plan) >= 1


def test_side_and_years():
    assert slot_side("RB", "FB") == "right" and slot_side("LW", "W") == "left" and slot_side("LCB", "CB") == ""
    assert [years_ru(n) for n in (21, 32, 35, 12)] == ["21 год", "32 года", "35 лет", "12 лет"]
