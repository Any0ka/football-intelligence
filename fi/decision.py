"""Shortlist: candidates for each needed slot ranked by TOPSIS (the method from Assignment 4), a budget plan,
and how stable the leaders are when the criterion weights change.

Hard rules come first (a candidate must be an upgrade on the current player, young enough, affordable, with a
current market value); the ranking then trades off fit, undervaluation, age and reliability.
"""
from __future__ import annotations

from itertools import product
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# criterion -> (weight, higher is better)
CRITERIA: Dict[str, Tuple[float, bool]] = {
    "fit": (0.45, True),           # need-weighted percentile: how well he closes this slot's gaps
    "gap": (0.30, True),           # log10(fair value / market value): how much cheaper than players like him
    "age": (0.10, False),
    "role_minutes": (0.15, True),  # more minutes in the role - more trustworthy numbers
}
CRITERIA_RU = {"fit": "соответствие", "gap": "недооценённость", "age": "возраст", "role_minutes": "минуты в роли"}
MAX_AGE = 29
MAX_PRICE = 50e6
SIDE_SHARE = 0.6           # a right back must have played at least 60 % of his full-back minutes on the right


def topsis(df: pd.DataFrame, criteria: Dict[str, Tuple[float, bool]] = CRITERIA) -> pd.Series:
    """Closeness to the ideal candidate (1 = best on every criterion).
    Min-max normalisation, not the vector one: undervaluation is signed (a player can be overvalued), and
    dividing a signed column by its norm would give it a far larger spread than the others - its weight
    would no longer mean what it says. After min-max every criterion spans 0..1 among the candidates."""
    cols = list(criteria)
    X = df[cols].to_numpy(float)
    w = np.array([criteria[c][0] for c in cols])
    w = w / w.sum()
    lo, hi = X.min(axis=0), X.max(axis=0)
    R = (X - lo) / np.where(hi > lo, hi - lo, 1)
    benefit = np.array([criteria[c][1] for c in cols])
    V = np.where(benefit, R, 1 - R) * w
    d_best = np.sqrt(((V - w) ** 2).sum(axis=1))          # ideal: 1 on every criterion
    d_worst = np.sqrt((V ** 2).sum(axis=1))               # anti-ideal: 0 on every criterion
    return pd.Series(d_worst / np.where(d_best + d_worst == 0, 1, d_best + d_worst), index=df.index)


def fit_score(pct: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
    return sum(pct[f"pct_{m}"] * w for m, w in weights.items())


def candidates(players: pd.DataFrame, need: pd.Series, team: str, incumbent_fit: float,
               max_age: float = MAX_AGE, max_price: float = MAX_PRICE) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Players of the slot's group that pass the hard rules; returns them and how many each rule removed."""
    c = players[(players["group"] == need["group"]) & players["reliable"]].copy()
    c["fit"] = fit_score(c, need["weights"])
    c["role_minutes"] = c["minutes"]
    steps = {"в роли ≥900 мин": len(c)}
    rules = [
        ("не из своего клуба", c["team"] != team),
        ("нужная сторона", c[f"{need['side']}_share"] >= SIDE_SHARE if need["side"] else None),
        ("есть свежая стоимость", c["value"].notna() & ~c["stale"].fillna(True)),
        (f"не старше {max_age}", c["age"] <= max_age),
        (f"стоимость ≤ €{max_price / 1e6:.0f} млн", c["value"] <= max_price),
        ("лучше текущего игрока", c["fit"] > incumbent_fit),
    ]
    for label, mask in rules:
        if mask is not None:
            c = c[mask.reindex(c.index)]
            steps[label] = len(c)
    return c, steps


def rank(c: pd.DataFrame, criteria: Dict[str, Tuple[float, bool]] = CRITERIA) -> pd.DataFrame:
    if c.empty:
        return c.assign(score=[])
    return c.assign(score=topsis(c, criteria)).sort_values("score", ascending=False)


def stability(c: pd.DataFrame, n: int = 2000, seed: int = 0, top: int = 3) -> pd.Series:
    """Share of random weight vectors (uniform over all weightings) under which each candidate makes the top."""
    if c.empty:
        return pd.Series(dtype=float)
    rng = np.random.default_rng(seed)
    hits = pd.Series(0, index=c.index)
    names = list(CRITERIA)
    for w in rng.dirichlet(np.ones(len(names)), size=n):
        crit = {k: (wk, CRITERIA[k][1]) for k, wk in zip(names, w)}
        hits[topsis(c, crit).nlargest(top).index] += 1
    return hits / n


def budget_plan(ranked: Dict[str, pd.DataFrame], budget: float, depth: int = 8) -> List[Tuple[str, int]]:
    """One player per slot, maximising the sum of TOPSIS scores within the budget (exhaustive over each
    slot's top `depth`; a slot may stay empty if nobody fits the money)."""
    slots = [s for s, r in ranked.items()]
    options = [[None] + list(ranked[s].index[:depth]) for s in slots]
    best, best_score = [], -1.0
    for combo in product(*options):
        cost = sum(ranked[s].at[i, "value"] for s, i in zip(slots, combo) if i is not None)
        if cost > budget:
            continue
        score = sum(ranked[s].at[i, "score"] for s, i in zip(slots, combo) if i is not None)
        if score > best_score:
            best, best_score = [(s, i) for s, i in zip(slots, combo) if i is not None], score
    return best
