"""Annual return of a club's squad as an asset, measured on Transfermarkt market values.

Revenue, wages and profit are not in open data, and the transfers table misses many big fees (in 2014 Chelsea's
Diego Costa, Fàbregas and the €49.5m sale of David Luiz are not there), so everything is measured by market value:
- the squad at the end of a season: players whose last appearance of the season was for the club;
- the return of a season: how the market value of the players who stayed (in the squad at the end of the season
  before and of this one) changed - the return of a portfolio without the buying and selling;
- arrivals and departures: players who joined or left the squad, by market value, not by fee.
A season runs from July to June and is named by its first year (2015 = 2015/16).
"""
from __future__ import annotations

from typing import Dict, Iterable

import pandas as pd

from . import events as fe
from .matching import TM

MIN_SQUAD = 15          # fewer players: the club spent the season outside the leagues the data covers (relegated)


def season_of(dates: pd.Series) -> pd.Series:
    return dates.dt.year - (dates.dt.month < 7)


def appearances() -> pd.DataFrame:
    """Every club appearance (player, club, date, competition); cached because the CSV is 45 MB."""
    path = fe.CACHE / "tm_appearances.parquet"
    if not path.exists():
        ap = pd.read_csv(TM / "appearances.csv.gz", usecols=["player_id", "player_club_id", "date", "competition_id"],
                         parse_dates=["date"])
        ap.rename(columns={"player_club_id": "club_id"}).to_parquet(path)
    ap = pd.read_parquet(path)
    return ap.assign(season=season_of(ap["date"]))


def squads(ap: pd.DataFrame) -> pd.DataFrame:
    """(season, club_id, player_id): the club of each player's last appearance of the season."""
    last = ap.sort_values("date").groupby(["season", "player_id"], as_index=False).last()
    return last[["season", "club_id", "player_id"]]


def season_values() -> pd.DataFrame:
    """(season, player_id, value): the last market value inside the season."""
    v = pd.read_csv(TM / "player_valuations.csv.gz", usecols=["player_id", "date", "market_value_in_eur"],
                    parse_dates=["date"])
    v = v.assign(season=season_of(v["date"])).sort_values("date")
    return (v.groupby(["season", "player_id"], as_index=False).last()
            .rename(columns={"market_value_in_eur": "value"})[["season", "player_id", "value"]])


def player_names() -> pd.Series:
    return pd.read_csv(TM / "players.csv.gz", usecols=["player_id", "name"]).set_index("player_id")["name"]


def with_league(ret: pd.DataFrame, ap: pd.DataFrame, codes: Iterable[str]) -> pd.DataFrame:
    """Adds the club's league that season, the league median return and the club's place by return in it."""
    out = ret.join(club_leagues(ap, codes).rename("league"), on=["club_id", "season"])
    ok = out.dropna(subset=["league", "ret"])
    by = ok.groupby(["league", "season"])["ret"]
    out = out.join(by.median().rename("median"), on=["league", "season"]).join(by.size().rename("of"),
                                                                               on=["league", "season"])
    out["rank"] = by.rank(ascending=False, method="min")
    return out


def club_ids(links: pd.DataFrame, ap: pd.DataFrame, league_code: str, season: int = 2015) -> Dict[str, int]:
    """StatsBomb team -> Transfermarkt club id: the club its matched players appeared for in that league and season."""
    a = (ap[(ap["competition_id"] == league_code) & (ap["season"] == season)][["player_id", "club_id"]]
         .drop_duplicates().rename(columns={"player_id": "tm_player_id"}))
    m = links.dropna(subset=["tm_player_id"]).merge(a, on="tm_player_id")
    return m.groupby("team")["club_id"].agg(lambda s: int(s.mode().iloc[0])).to_dict()


def club_leagues(ap: pd.DataFrame, codes: Iterable[str]) -> pd.Series:
    """(club_id, season) -> the league (of `codes`) where the club played that season."""
    a = ap[ap["competition_id"].isin(list(codes))]
    return a.groupby(["club_id", "season"])["competition_id"].agg(lambda s: s.mode().iloc[0])


def moves(sq: pd.DataFrame, values: pd.DataFrame) -> pd.DataFrame:
    """Per (season, club, player): stayed / joined / left, with the value at the end of this season (value) and
    of the season before (value_prev)."""
    now = sq.merge(values, on=["season", "player_id"], how="left")
    before = now.assign(season=now["season"] + 1).rename(columns={"value": "value_prev"})
    m = now.merge(before, on=["season", "club_id", "player_id"], how="outer", indicator=True)
    m["status"] = m["_merge"].map({"both": "stayed", "left_only": "joined", "right_only": "left"}).astype(str)
    m = m.drop(columns="_merge")
    return m[m["season"].between(sq["season"].min() + 1, sq["season"].max())]


def returns(mv: pd.DataFrame) -> pd.DataFrame:
    """One row per (club_id, season): squad value at the end of the season, return of the players who stayed,
    arrivals and departures by market value."""
    stayed = mv["status"].eq("stayed") & mv["value"].notna() & mv["value_prev"].notna()
    joined, left = mv["status"].eq("joined"), mv["status"].eq("left")
    in_squad = ~left
    x = mv.assign(in_squad=in_squad, in_prev=~joined, squad_value=mv["value"].where(in_squad),
                  stayed=stayed, v0=mv["value_prev"].where(stayed), v1=mv["value"].where(stayed),
                  joined=joined, joined_value=mv["value"].where(joined),
                  left=left, left_value=mv["value_prev"].where(left))
    out = x.groupby(["club_id", "season"]).agg(
        squad=("in_squad", "sum"), squad_prev=("in_prev", "sum"), squad_value=("squad_value", "sum"),
        stayed=("stayed", "sum"), v0=("v0", "sum"), v1=("v1", "sum"), joined=("joined", "sum"), joined_value=("joined_value", "sum"),
        left=("left", "sum"), left_value=("left_value", "sum"))
    out["ret"] = out["v1"] / out["v0"] - 1
    # outside the covered leagues the squad is only the cup players: no squad that season, and no comparison with it
    covered = out["squad"] >= MIN_SQUAD
    both = covered & (out["squad_prev"] >= MIN_SQUAD)
    out.loc[~covered, ["squad", "squad_value"]] = float("nan")
    out.loc[~both, ["stayed", "v0", "v1", "joined", "joined_value", "left", "left_value", "ret"]] = float("nan")
    out.loc[out["v0"] <= 0, "ret"] = float("nan")
    return out.reset_index()
