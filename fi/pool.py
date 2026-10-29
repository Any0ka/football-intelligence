"""Candidate pool: players of the top five leagues 2015/16, measured exactly like the diagnosed team.

Open data covers whole seasons of the Premier League, La Liga, Serie A and Ligue 1; of the Bundesliga only
Bayer Leverkusen's 34 matches are open, so a team is kept only when (almost) its whole season is in the data -
otherwise its players' numbers would rest on two matches.
"""
from __future__ import annotations

from typing import Dict, Iterable, Tuple

import pandas as pd

from . import events as fe, matching as mt, metrics as fm, statsbomb as sb, tactics as ft, valuation as fv

SEASON = "2015/2016"
# StatsBomb competition -> Transfermarkt competition code (used to link clubs)
LEAGUES: Dict[str, str] = {"Premier League": "GB1", "La Liga": "ES1", "Serie A": "IT1", "Ligue 1": "FR1",
                           "1. Bundesliga": "L1"}
LEAGUE_RU = {"Premier League": "АПЛ", "La Liga": "Ла Лига", "Serie A": "Серия А", "Ligue 1": "Лига 1",
             "1. Bundesliga": "Бундеслига"}
FULL_SEASON = 30            # matches of a team in the data


def sides(spells: pd.DataFrame) -> pd.DataFrame:
    """Share of a player's minutes in a group played on the right / left (a right back is not a left back)."""
    sp = spells.assign(group=spells["position"].map(fm.GROUP_OF))
    sp["right"] = sp["position"].str.startswith("Right") * sp["minutes"]
    sp["left"] = sp["position"].str.startswith("Left") * sp["minutes"]
    s = sp.groupby(["player_id", "team", "group"])[["minutes", "right", "left"]].sum()
    out = pd.DataFrame({"right_share": s["right"] / s["minutes"], "left_share": s["left"] / s["minutes"]})
    return out.fillna(0).reset_index()


def _tag(competition: str) -> str:
    return f"{competition}_{SEASON}".replace(" ", "_").replace("/", "-").replace(".", "").lower()


def downloaded(competition: str) -> bool:
    """All events and lineups of the competition-season are on disk."""
    s = sb.find_season(competition, SEASON)
    ids = [m["match_id"] for m in sb.matches(s["competition_id"], s["season_id"])]
    return all((sb.RAW / k / f"{m}.json").exists() for m in ids for k in ("events", "lineups"))


def league(competition: str, refresh: bool = False) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(players, teams) of one league: per-90 table with side shares and team strength, cached as parquet."""
    pp, tp = fe.CACHE / f"pool_{_tag(competition)}_players.parquet", fe.CACHE / f"pool_{_tag(competition)}_teams.parquet"
    if not refresh and pp.exists() and tp.exists():
        return pd.read_parquet(pp), pd.read_parquet(tp)
    matches, ev, spells = fe.season(competition, SEASON)
    teams = ft.league_table(matches, ev)
    teams = teams[teams["matches"] >= FULL_SEASON].copy()
    teams["ppg"] = teams["pts"] / teams["matches"]
    teams["xgd90"] = teams["xgd"] / teams["matches"]
    teams["league"] = competition
    teams = teams.reset_index()

    players = fm.player_table(ev, spells)
    players = players[players["team"].isin(teams["team"])]
    players = players.merge(sides(spells), on=["player_id", "team", "group"], how="left")
    country = spells.groupby("player_id")["country"].first()
    players["country"] = players["player_id"].map(country)
    players["league"] = competition
    players = players.merge(teams[["team", "ppg", "xgd90", "place"]].rename(
        columns={"ppg": "team_ppg", "xgd90": "team_xgd90", "place": "team_place"}), on="team", how="left")
    players.to_parquet(pp, index=False)
    teams.to_parquet(tp, index=False)
    return players, teams


def load(leagues: Iterable[str] = LEAGUES) -> Tuple[pd.DataFrame, pd.DataFrame]:
    parts = [league(c) for c in leagues]
    return (pd.concat([p for p, _ in parts], ignore_index=True), pd.concat([t for _, t in parts], ignore_index=True))


def links(competition: str, refresh: bool = False) -> pd.DataFrame:
    """StatsBomb player -> Transfermarkt id, age and market value at the decision date (cached per league)."""
    path = fe.CACHE / f"links_{_tag(competition)}.parquet"
    if not refresh and path.exists():
        return pd.read_parquet(path)
    players, _ = league(competition)
    sbp = (players.groupby(["player_id", "team"])
           .agg(player=("player", "first"), nickname=("nickname", "first"), country=("country", "first"),
                minutes=("minutes", "sum"), league=("league", "first")).reset_index())
    out = mt.match_players(sbp, clubs=mt.club_map(sbp))
    ids = out["tm_player_id"]
    out = pd.concat([out, fv.values_at(ids)], axis=1)
    out["age"] = fv.ages(ids)
    out.to_parquet(path, index=False)
    return out
