"""Player performance per position group, per 90 minutes, compared with the league.

Different positions are judged by different metrics (a centre-back is not a striker), defensive
actions are adjusted for the opponent's possession (a team that has the ball less defends more),
and a player needs enough minutes in a group before his numbers mean anything.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

GROUPS: Dict[str, List[str]] = {
    "GK": ["Goalkeeper"],
    "CB": ["Center Back", "Left Center Back", "Right Center Back"],
    "FB": ["Left Back", "Right Back", "Left Wing Back", "Right Wing Back"],
    "CM": ["Center Defensive Midfield", "Left Defensive Midfield", "Right Defensive Midfield",
           "Center Midfield", "Left Center Midfield", "Right Center Midfield"],
    "AM": ["Center Attacking Midfield", "Left Attacking Midfield", "Right Attacking Midfield"],
    "W": ["Left Wing", "Right Wing", "Left Midfield", "Right Midfield"],
    "CF": ["Center Forward", "Left Center Forward", "Right Center Forward", "Secondary Striker"],
}
GROUP_OF = {pos: g for g, ps in GROUPS.items() for pos in ps}
GROUP_NAMES = {"GK": "вратарь", "CB": "центральный защитник", "FB": "крайний защитник", "CM": "центральный полузащитник",
               "AM": "атакующий полузащитник", "W": "вингер", "CF": "нападающий"}

# metric -> (Russian label, higher is better)
METRICS: Dict[str, Tuple[str, bool]] = {
    "goals_prevented": ("предотвращённые голы (xG ударов в створ − пропущенные)", True),
    "save_pct": ("% отражённых ударов в створ", True),
    "def_actions_padj": ("отборы + перехваты + блоки + выносы (с поправкой на владение)", True),
    "tackle_int_padj": ("выигранные отборы + перехваты (с поправкой на владение)", True),
    "recoveries_padj": ("подборы мяча (с поправкой на владение)", True),
    "aerial_win_pct": ("% выигранной борьбы в воздухе", True),
    "dribbled_past": ("сколько раз обыграли", False),
    "pass_pct": ("точность передач", True),
    "prog_passes": ("передачи вперёд, продвигающие мяч", True),
    "prog_carries": ("проходы с мячом вперёд", True),
    "pressures": ("давление на соперника", True),
    "losses": ("потери (отобрали + неудачный приём)", False),
    "xa": ("xA — ожидаемые голевые передачи", True),
    "key_passes": ("передачи под удар", True),
    "dribbles": ("удачные обводки", True),
    "npxg": ("xG без пенальти", True),
    "shots": ("удары", True),
    "finishing": ("голы − xG (реализация)", True),
}
ROLE_METRICS: Dict[str, List[str]] = {
    "GK": ["goals_prevented", "save_pct"],
    "CB": ["def_actions_padj", "aerial_win_pct", "dribbled_past", "pass_pct", "prog_passes"],
    "FB": ["tackle_int_padj", "dribbled_past", "prog_passes", "prog_carries", "xa"],
    "CM": ["tackle_int_padj", "recoveries_padj", "pass_pct", "prog_passes", "pressures", "losses"],
    "AM": ["xa", "key_passes", "npxg", "dribbles", "prog_carries", "losses"],
    "W": ["xa", "key_passes", "npxg", "dribbles", "prog_carries", "losses"],
    "CF": ["npxg", "finishing", "shots", "xa", "pressures", "aerial_win_pct"],
}
MIN_MINUTES = 900          # ten full matches in a group before the per-90 numbers are trusted
WON = {"Won", "Success", "Success In Play", "Success Out"}


def _progressive(df: pd.DataFrame) -> pd.Series:
    """Moves the ball at least 10 yards forward into the opponent half, or into the box."""
    fwd = (df["end_x"] - df["x"] >= 10) & (df["end_x"] >= 60)
    box = (df["end_x"] >= 102) & df["end_y"].between(18, 62)
    return fwd | box


def possession_share(ev: pd.DataFrame) -> pd.DataFrame:
    """Per match and team: share of the match's passes - a simple, robust possession estimate."""
    p = ev[ev["type"] == "Pass"].groupby(["match_id", "team"]).size().rename("passes").reset_index()
    p["share"] = p["passes"] / p.groupby("match_id")["passes"].transform("sum")
    return p[["match_id", "team", "share"]]


def player_table(ev: pd.DataFrame, spells: pd.DataFrame) -> pd.DataFrame:
    """One row per (player, team, position group) with minutes and per-90 metrics."""
    ev = ev.copy()
    ev["group"] = ev["position"].map(GROUP_OF)
    poss = possession_share(ev)
    # possession adjustment: actions scale by 0.5 / opponent share (opponent has the ball 50 % -> x1)
    adj = poss.merge(poss, on="match_id", suffixes=("", "_opp"))
    adj = adj[adj["team"] != adj["team_opp"]][["match_id", "team", "share_opp"]]
    ev = ev.merge(adj, on=["match_id", "team"], how="left")
    ev["padj"] = (0.5 / ev["share_opp"].clip(0.2, 0.8)).fillna(1.0)

    sp = spells.copy()
    sp["group"] = sp["position"].map(GROUP_OF)
    minutes = sp.groupby(["player_id", "team", "group"])["minutes"].sum()

    keys = ["player_id", "team", "group"]
    is_ = lambda t: ev["type"] == t
    passes = ev[is_("Pass") & ~ev["sub_type"].isin(["Throw-in", "Goal Kick", "Corner", "Free Kick", "Kick Off"])]
    completed = passes[passes["outcome"].isna()]
    shots = ev[is_("Shot")]
    np_shots = shots[shots["sub_type"] != "Penalty"]
    xa = shots.dropna(subset=["shot_key_pass_id"]).groupby("shot_key_pass_id")["shot_xg"].sum()
    passes_all = ev[is_("Pass")]
    xa_by = passes_all.assign(xa=passes_all["id"].map(xa).fillna(0.0)).groupby(keys)["xa"].sum()

    def count(mask, weight=None):
        d = ev[mask]
        return (d.groupby(keys)[weight].sum() if weight else d.groupby(keys).size())

    duels = is_("Duel")
    tackles_won = duels & (ev["sub_type"] == "Tackle") & ev["outcome"].isin(WON)
    interceptions = is_("Interception") & ev["outcome"].isin(WON)
    aerial_lost = duels & (ev["sub_type"] == "Aerial Lost")
    t = pd.DataFrame({
        "minutes": minutes,
        "passes": passes.groupby(keys).size(),
        "passes_ok": completed.groupby(keys).size(),
        "prog_passes": completed[_progressive(completed)].groupby(keys).size(),
        "prog_carries": count(is_("Carry") & _progressive(ev)),
        "key_passes": count(is_("Pass") & ev["pass_shot_assist"]),
        "xa": xa_by,
        "npxg": np_shots.groupby(keys)["shot_xg"].sum(),
        "shots": shots.groupby(keys).size(),
        "goals": shots[shots["outcome"] == "Goal"].groupby(keys).size(),
        "xg": shots.groupby(keys)["shot_xg"].sum(),
        "dribbles": count(is_("Dribble") & (ev["outcome"] == "Complete")),
        "tackle_int_padj": count(tackles_won | interceptions, "padj"),
        "def_actions_padj": count(tackles_won | interceptions | is_("Block") | is_("Clearance"), "padj"),
        "recoveries_padj": count(is_("Ball Recovery"), "padj"),
        "aerial_won": count(ev["aerial_won"]),
        "aerial_lost": count(aerial_lost),
        "dribbled_past": count(is_("Dribbled Past")),
        "pressures": count(is_("Pressure")),
        "losses": count(is_("Dispossessed") | is_("Miscontrol")),
    }).fillna(0.0)
    t = t[t["minutes"] > 0].reset_index()
    per90 = t["minutes"] / 90
    out = t[keys + ["minutes"]].copy()
    for c in ["prog_passes", "prog_carries", "key_passes", "xa", "npxg", "shots", "dribbles", "tackle_int_padj",
              "def_actions_padj", "recoveries_padj", "dribbled_past", "pressures", "losses"]:
        out[c] = t[c] / per90
    out["pass_pct"] = (t["passes_ok"] / t["passes"].replace(0, np.nan)).fillna(0)
    duels_air = t["aerial_won"] + t["aerial_lost"]
    out["aerial_win_pct"] = (t["aerial_won"] / duels_air.replace(0, np.nan)).fillna(0.5)
    out["finishing"] = (t["goals"] - t["xg"]) / per90
    out["goals"], out["xg"] = t["goals"], t["xg"]
    out = out.merge(goalkeeping(ev, spells), on=["player_id", "team", "group"], how="left")
    names = spells.groupby("player_id").agg(player=("player", "first"), nickname=("nickname", "first"))
    out = out.merge(names, left_on="player_id", right_index=True, how="left")
    out["name"] = out["nickname"].fillna(out["player"])
    return out


def goalkeeping(ev: pd.DataFrame, spells: pd.DataFrame) -> pd.DataFrame:
    """Shots faced by each goalkeeper while he was on the pitch."""
    gk = spells[spells["position"] == "Goalkeeper"]
    shots = ev[(ev["type"] == "Shot") & ev["outcome"].isin(["Goal", "Saved", "Saved To Post", "Saved Off Target"])]
    rows = []
    for g in gk.itertuples():
        on = shots[(shots["match_id"] == g.match_id) & (shots["team"] != g.team)
                   & (shots["minute"] >= g.start) & (shots["minute"] < g.end)]
        rows.append({"player_id": g.player_id, "team": g.team, "group": "GK", "faced": len(on),
                     "conceded": int((on["outcome"] == "Goal").sum()), "xg_faced": on["shot_xg"].sum(),
                     "minutes_gk": g.minutes})
    if not rows:
        return pd.DataFrame(columns=["player_id", "team", "group", "goals_prevented", "save_pct"])
    d = pd.DataFrame(rows).groupby(["player_id", "team", "group"]).sum().reset_index()
    d["goals_prevented"] = (d["xg_faced"] - d["conceded"]) / (d["minutes_gk"] / 90)
    d["save_pct"] = 1 - d["conceded"] / d["faced"].replace(0, np.nan)
    return d[["player_id", "team", "group", "goals_prevented", "save_pct"]]


def percentiles(table: pd.DataFrame, min_minutes: int = MIN_MINUTES, pool_teams=None) -> pd.DataFrame:
    """Percentile of each role metric among the benchmark players of the same group with enough minutes:
    the whole league by default, or only the players of `pool_teams` (e.g. the top six - the level a
    title contender is measured against). Role score = mean percentile of the group's metrics (50 = median)."""
    out = []
    for g, metrics in ROLE_METRICS.items():
        sub = table[(table["group"] == g)].copy()
        pool = sub[sub["minutes"] >= min_minutes]
        if pool_teams is not None:
            pool = pool[pool["team"].isin(pool_teams)]
        if pool.empty:
            continue
        for m in metrics:
            higher = METRICS[m][1]
            ref = pool[m].to_numpy()
            pct = sub[m].apply(lambda v: (ref < v).mean() * 100 + (ref == v).mean() * 50)
            sub[f"pct_{m}"] = pct if higher else 100 - pct
        sub["role_score"] = sub[[f"pct_{m}" for m in metrics]].mean(axis=1)
        sub["reliable"] = sub["minutes"] >= min_minutes
        out.append(sub)
    return pd.concat(out, ignore_index=True)
