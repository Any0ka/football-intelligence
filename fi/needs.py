"""From the diagnosis to a shopping list: which slots of the formation need a player and what he must be good at.

A slot needs a player when the people who played it are clearly below the benchmark (the top six), or when
its main player is old enough that the club has to plan a replacement. What the new player must be good at
follows from where the current ones fall short: every role metric counts, the metrics with the largest gap
count up to twice as much.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import metrics as fm

SLOT_MIN = 200             # a few cameo minutes in a slot say nothing about it
WEAK = 45                  # slot score below this (50 = benchmark median) is a performance need
OLD = 31                   # main player this old in the summer is a succession need


def years_ru(n: float) -> str:
    n = int(n)
    word = "год" if n % 10 == 1 and n % 100 != 11 else "года" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "лет"
    return f"{n} {word}"


def slot_side(slot: str, group: str) -> str:
    """Full backs and wingers have a side; centre-backs, midfielders and strikers are judged without one."""
    if group in ("FB", "W") and slot[:1] in "RL":
        return "right" if slot[0] == "R" else "left"
    return ""


def position_slots(spells: pd.DataFrame, pct: pd.DataFrame, team: str, layout,
                   slot_ids: Optional[Dict[int, int]] = None):
    """For each slot of the formation: who played there (minutes) and the minutes-weighted role score.
    slot_ids maps every StatsBomb position id to a slot (shape.slot_of), so minutes in positions the
    formation does not list (a holding midfielder in a 4-2-3-1 week) still count for the nearest slot.
    Returns (slots for the pitch picture, one row per player and slot with his percentiles)."""
    sp = spells[spells["team"] == team]
    slots, rows = [], []
    for i, pos in enumerate(layout):
        played = sp[sp["position_id"].map(slot_ids) == i] if slot_ids else sp[sp["position_id"].isin(pos.statsbomb)]
        by_player = played.groupby("player_id")["minutes"].sum().sort_values(ascending=False)
        players, scores, weights = [], [], []
        for pid, mins in by_player.items():
            mine = played[played["player_id"] == pid]
            group = fm.GROUP_OF[mine["position"].iloc[0]]
            row = pct[(pct["player_id"] == pid) & (pct["team"] == team) & (pct["group"] == group)]
            name = row["name"].iloc[0] if len(row) else mine["nickname"].fillna(mine["player"]).iloc[0]
            players.append((name, mins))
            if len(row) and mins >= SLOT_MIN:
                scores.append(float(row["role_score"].iloc[0]))
                weights.append(mins)
                rows.append({"slot": pos.name, "player_id": pid, "player": name, "slot_minutes": round(mins),
                             "group": group, "role_score": round(float(row["role_score"].iloc[0]), 1),
                             **{f"pct_{m}": round(float(row[f"pct_{m}"].iloc[0])) for m in fm.ROLE_METRICS[group]}})
        score = float(np.average(scores, weights=weights)) if scores else None
        slots.append({"position_ids": pos.statsbomb, "score": score, "players": players})
    return slots, pd.DataFrame(rows)


def needs(layout, slots: List[Dict], detail: pd.DataFrame, ages: Dict[int, float]) -> pd.DataFrame:
    """One row per slot: score, main player and his age, whether it is a need and why, metric weights."""
    out = []
    for pos, slot in zip(layout, slots):
        d = detail[detail["slot"] == pos.name]
        if d.empty:
            continue
        group = d.groupby("group")["slot_minutes"].sum().idxmax()
        d = d[d["group"] == group]
        main = d.loc[d["slot_minutes"].idxmax()]
        age = ages.get(int(main["player_id"]))
        reasons = []
        if slot["score"] is not None and slot["score"] < WEAK:
            reasons.append(f"ниже топ-6 ({slot['score']:.0f})")
        if age is not None and age >= OLD:
            reasons.append(f"{main['player'].split()[-1]} — {years_ru(age)}")
        gaps = {m: float(np.average(d[f"pct_{m}"], weights=d["slot_minutes"])) for m in fm.ROLE_METRICS[group]}
        raw = {m: 1 + max(0.0, 50 - p) / 50 for m, p in gaps.items()}
        total = sum(raw.values())
        out.append({"slot": pos.name, "group": group, "side": slot_side(pos.name, group),
                    "score": slot["score"], "main": main["player"], "main_id": int(main["player_id"]), "main_age": age,
                    "need": bool(reasons), "reason": "; ".join(reasons),
                    "incumbent_pct": gaps, "weights": {m: w / total for m, w in raw.items()}})
    return pd.DataFrame(out)
