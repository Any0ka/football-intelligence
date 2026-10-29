"""StatsBomb JSON -> flat pandas tables: one row per event, one row per player-position spell.

The flat event table keeps what the analysis needs (who, what, where, outcome, xG) and is cached
as parquet, so a season of ~1.3M events loads in seconds after the first pass.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from . import statsbomb as sb

CACHE = sb.ROOT / "data" / "cache"


def _xy(v, i):
    return v[i] if isinstance(v, list) and len(v) > i else None


def _clock(s: str) -> float:
    """'67:30' -> 67.5 minutes."""
    m, sec = s.split(":")
    return int(m) + int(sec) / 60


def flatten(match: dict, events: List[dict]) -> List[Dict]:
    rows = []
    for e in events:
        t = e["type"]["name"]
        sub = e.get(t.lower().replace(" ", "_").replace("*", ""), {}) or {}
        end = sub.get("end_location") if isinstance(sub, dict) else None
        rows.append({
            "match_id": match["match_id"],
            "id": e["id"],
            "index": e["index"],
            "period": e["period"],
            "minute": e["minute"],
            "second": e["second"],
            "type": t,
            "team": e["team"]["name"],
            "possession_team": e["possession_team"]["name"],
            "possession": e["possession"],
            "play_pattern": e["play_pattern"]["name"],
            "player": (e.get("player") or {}).get("name"),
            "player_id": (e.get("player") or {}).get("id"),
            "position": (e.get("position") or {}).get("name"),
            "x": _xy(e.get("location"), 0),
            "y": _xy(e.get("location"), 1),
            "end_x": _xy(end, 0),
            "end_y": _xy(end, 1),
            "under_pressure": bool(e.get("under_pressure", False)),
            "counterpress": bool(e.get("counterpress", False)),
            "outcome": ((sub.get("outcome") or {}).get("name") if isinstance(sub, dict) else None),
            "sub_type": ((sub.get("type") or {}).get("name") if isinstance(sub, dict) else None),
            "body_part": ((sub.get("body_part") or {}).get("name") if isinstance(sub, dict) else None),
            "pass_recipient": ((sub.get("recipient") or {}).get("name") if t == "Pass" else None),
            "pass_length": sub.get("length") if t == "Pass" else None,
            "pass_height": ((sub.get("height") or {}).get("name") if t == "Pass" else None),
            "pass_cross": bool(sub.get("cross", False)) if t == "Pass" else False,
            "pass_switch": bool(sub.get("switch", False)) if t == "Pass" else False,
            "pass_through_ball": bool(sub.get("through_ball", False)) if t == "Pass" else False,
            "pass_shot_assist": bool(sub.get("shot_assist", False)) if t == "Pass" else False,
            "pass_goal_assist": bool(sub.get("goal_assist", False)) if t == "Pass" else False,
            "shot_xg": sub.get("statsbomb_xg") if t == "Shot" else None,
            "shot_first_time": bool(sub.get("first_time", False)) if t == "Shot" else False,
            "shot_key_pass_id": sub.get("key_pass_id") if t == "Shot" else None,
            "aerial_won": bool(sub.get("aerial_won", False)) if isinstance(sub, dict) else False,
            "dribble_nutmeg": bool(sub.get("nutmeg", False)) if t == "Dribble" else False,
            "formation": str((e.get("tactics") or {}).get("formation") or "") or None,   # Starting XI, Tactical Shift
        })
    return rows


def match_frame(matches: List[dict]) -> pd.DataFrame:
    rows = []
    for m in matches:
        rows.append({
            "match_id": m["match_id"], "date": pd.Timestamp(m["match_date"]), "week": m.get("match_week"),
            "home": m["home_team"]["home_team_name"], "away": m["away_team"]["away_team_name"],
            "home_score": m["home_score"], "away_score": m["away_score"],
            "home_manager": ", ".join(x["name"] for x in m["home_team"].get("managers") or []),
            "away_manager": ", ".join(x["name"] for x in m["away_team"].get("managers") or []),
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def spells(match: dict, lineups: List[dict]) -> List[Dict]:
    """Who played where and for how long (StatsBomb lineups carry position spells with from/to clocks)."""
    rows = []
    for team in lineups:
        for p in team["lineup"]:
            for pos in p.get("positions") or []:
                start = _clock(pos["from"])
                # an open spell ends at the final whistle; extra time is rare in the league, 95' is a safe cap
                stop = _clock(pos["to"]) if pos.get("to") else 95.0
                rows.append({
                    "match_id": match["match_id"], "team": team["team_name"], "player_id": p["player_id"],
                    "player": p["player_name"], "nickname": p.get("player_nickname"),
                    "country": (p.get("country") or {}).get("name"),
                    "position": pos["position"], "position_id": pos["position_id"],
                    "start": start, "end": stop, "minutes": max(0.0, stop - start),
                    "start_reason": pos.get("start_reason"), "end_reason": pos.get("end_reason"),
                })
    return rows


def season(competition: str, season_name: str, refresh: bool = False):
    """(matches, events, spells) for a whole competition-season, cached as parquet."""
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = f"{competition}_{season_name}".replace(" ", "_").replace("/", "-").lower()
    paths = {k: CACHE / f"{tag}_{k}.parquet" for k in ("matches", "events", "spells")}
    if not refresh and all(p.exists() for p in paths.values()):
        return tuple(pd.read_parquet(paths[k]) for k in ("matches", "events", "spells"))
    s = sb.find_season(competition, season_name)
    ms = sb.matches(s["competition_id"], s["season_id"])
    sb.download([m["match_id"] for m in ms])
    ev, sp = [], []
    for m in ms:
        ev.extend(flatten(m, sb.events(m["match_id"])))
        sp.extend(spells(m, sb.lineups(m["match_id"])))
    out = (match_frame(ms), pd.DataFrame(ev), pd.DataFrame(sp))
    for k, df in zip(("matches", "events", "spells"), out):
        df.to_parquet(paths[k], index=False)
    return out
