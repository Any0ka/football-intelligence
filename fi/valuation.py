"""Market value at the decision date and a "fair value" model: what the market pays for players like this one.

A player is undervalued when his market value is well below what the model predicts from his age, minutes,
role, output, team and league. Each player's prediction comes from a model that never saw him (out-of-fold),
otherwise the model would partly memorise his own price. The model only learns how the market prices
performance; whatever it cannot see (injuries, contract length, reputation) also ends up in the gap, which
is why the gap is checked against what happened next (scripts/backtest.py).
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .matching import TM

DECISION_DATE = "2016-06-30"
STALE_DAYS = 300           # a valuation older than this at the decision date no longer reflects the player
NUMERIC = ["age", "age2", "minutes", "role_score", "npxg", "xa", "goals90", "prog", "def_actions_padj", "pass_pct",
           "team_ppg", "team_xgd90"]
CATEGORICAL = ["group", "league"]


def values_at(tm_ids: pd.Series, date: str = DECISION_DATE) -> pd.DataFrame:
    """Last market value on or before the date and the date of that valuation."""
    vals = pd.read_csv(TM / "player_valuations.csv.gz", parse_dates=["date"])
    last = vals[vals["date"] <= date].sort_values("date").groupby("player_id").last()
    out = pd.DataFrame({"value": tm_ids.map(last["market_value_in_eur"]), "value_date": tm_ids.map(last["date"])})
    out["stale"] = (pd.Timestamp(date) - out["value_date"]).dt.days > STALE_DAYS
    return out


def values_after(tm_ids: pd.Series, date: str, after: str = DECISION_DATE) -> pd.Series:
    """Last market value after the decision date and on or before `date` - for checking the decision only,
    never as an input to it. No valuation in that window (retired, dropped out of the data) -> NaN."""
    vals = pd.read_csv(TM / "player_valuations.csv.gz", parse_dates=["date"])
    v = vals[(vals["date"] > after) & (vals["date"] <= date)].sort_values("date")
    return tm_ids.map(v.groupby("player_id")["market_value_in_eur"].last())


def ages(tm_ids: pd.Series, date: str = DECISION_DATE) -> pd.Series:
    """Age in years at the date (date of birth does not change, so this leaks nothing from the future)."""
    dob = pd.read_csv(TM / "players.csv.gz", usecols=["player_id", "date_of_birth"],
                      parse_dates=["date_of_birth"]).set_index("player_id")["date_of_birth"]
    return (pd.Timestamp(date) - tm_ids.map(dob)).dt.days / 365.25


def photos(tm_ids: pd.Series) -> pd.Series:
    """Transfermarkt portrait URL. The page loads it from their server: the photos are not CC0 like the data, and
    they are today's, not 2016's. Transfermarkt's "no photo" silhouette becomes NaN so the page draws its own."""
    url = pd.read_csv(TM / "players.csv.gz", usecols=["player_id", "image_url"]).set_index("player_id")["image_url"]
    return tm_ids.map(url[~url.str.contains("/default.jpg", na=True, regex=False)])


def player_rows(pct: pd.DataFrame) -> pd.DataFrame:
    """One row per player: his main (team, group) by minutes, with total minutes over all his rows."""
    main = pct.sort_values("minutes", ascending=False).drop_duplicates("player_id").copy()
    main["role_minutes"] = main["minutes"]
    main["minutes"] = main["player_id"].map(pct.groupby("player_id")["minutes"].sum())
    main["goals90"] = main["goals"] / (main["role_minutes"] / 90)
    main["prog"] = main["prog_passes"] + main["prog_carries"]
    return main


def _design(df: pd.DataFrame) -> pd.DataFrame:
    x = df.assign(age2=(df["age"] - 26) ** 2)[NUMERIC].astype(float)
    return pd.concat([x, pd.get_dummies(df[CATEGORICAL].astype(str), dtype=float)], axis=1)


def fit_fair_value(df: pd.DataFrame, seed: int = 0) -> Tuple[pd.DataFrame, Dict]:
    """df: player rows with value and features. Returns df with fair_value / gap and a model report.
    Two models are compared by cross-validated error on log10(value); the better one gives the predictions."""
    X, y = _design(df), np.log10(df["value"].to_numpy())
    cv = KFold(5, shuffle=True, random_state=seed)
    models = {
        "ridge": make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-2, 3, 20))),
        "boosting": HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=400,
                                                  l2_regularization=1.0, random_state=seed),
    }
    report, preds = {}, {}
    for name, model in models.items():
        p = cross_val_predict(model, X, y, cv=cv)
        err = p - y
        preds[name] = p
        report[name] = {"r2": float(1 - (err ** 2).sum() / ((y - y.mean()) ** 2).sum()),
                        "median_x": float(10 ** np.median(np.abs(err)))}       # typical error as a factor (x1.6)
    best = max(report, key=lambda k: report[k]["r2"])
    out = df.copy()
    out["fair_value"] = 10 ** preds[best]
    out["gap"] = preds[best] - y                     # > 0: the market values him below players like him
    out["ratio"] = out["fair_value"] / out["value"]
    report["chosen"] = best
    report["n"] = int(len(df))
    return out, report
