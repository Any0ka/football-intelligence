"""Linking StatsBomb players to Transfermarkt players (market values).

StatsBomb lineups give a full legal name ("Francesc Fàbregas i Soler"), sometimes a nickname
("Cesc Fàbregas") and the nationality, but no date of birth. Transfermarkt gives the common name,
nationality and - in the valuation history - the club at the date of each valuation. So a player
is matched within the club he played for that season, by name similarity, with nationality as a
tie-breaker; players who changed clubs fall back to a league-wide search by name + nationality.
Every match keeps its method and score, so doubtful links can be inspected.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .statsbomb import ROOT

TM = ROOT / "data" / "raw" / "transfermarkt"
CLUB_NOISE = {"fc", "afc", "cf", "sc", "football", "club", "calcio", "1909", "1908"}
COUNTRY_ALIASES = {"korea republic": "south korea", "cote divoire": "cote d'ivoire", "ivory coast": "cote d'ivoire",
                   "united states of america": "united states", "republic of ireland": "ireland",
                   "congo dr": "dr congo", "congo, the democratic republic of the": "dr congo"}


def norm(s: Optional[str]) -> str:
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    for ch, rep in (("ø", "o"), ("Ø", "o"), ("ß", "ss"), ("ł", "l"), ("Ł", "l"), ("đ", "d"), ("ð", "d"), ("Ð", "d"),
                    ("þ", "th"), ("Þ", "th"), ("æ", "ae"), ("Æ", "ae"), ("ı", "i")):
        s = s.replace(ch, rep)
    s = re.sub(r"['’`´.]", "", s.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def club_key(name: str) -> str:
    return " ".join(t for t in norm(name).split() if t not in CLUB_NOISE)


def country_key(name: Optional[str]) -> str:
    k = norm(name)
    return norm(COUNTRY_ALIASES.get(k, k))


def name_score(sb_names: List[str], tm_name: str) -> float:
    """1.0 - same name; high when the Transfermarkt name is contained in the full StatsBomb name.
    A shared first name alone is not enough: without a matching surname the score is capped."""
    tm = norm(tm_name)
    tm_list = tm.split()
    tm_tokens = set(tm_list)
    if not tm_list:
        return 0.0
    best, surname_ok = 0.0, False
    for n in sb_names:
        s = norm(n)
        if not s:
            continue
        lst = s.split()
        tokens = set(lst)
        ratio = SequenceMatcher(None, s, tm).ratio()
        jacc = len(tokens & tm_tokens) / max(1, len(tokens | tm_tokens))
        contained = len(tm_tokens & tokens) / max(1, len(tm_tokens))       # all TM tokens present in SB name
        last = 1.0 if tm_list[-1] in tokens else 0.0
        best = max(best, ratio, jacc, 0.6 * contained + 0.4 * last if contained >= 1 else 0.0)
        # "Tim Krul" vs "Timothy Michael Krul": same surname, first name is a short form
        if lst[-1] == tm_list[-1] and (lst[0].startswith(tm_list[0]) or tm_list[0].startswith(lst[0])):
            best = max(best, 0.95)
        if contained >= 1 or last or any(SequenceMatcher(None, t, tm_list[-1]).ratio() >= 0.8 for t in lst[-2:]):
            surname_ok = True
    return best if surname_ok else min(best, 0.6)


def load_tm(start: str, end: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Transfermarkt players and their valuations, the valuations limited to [start, end]."""
    players = pd.read_csv(TM / "players.csv.gz", parse_dates=["date_of_birth"])
    vals = pd.read_csv(TM / "player_valuations.csv.gz", parse_dates=["date"])
    window = vals[(vals["date"] >= start) & (vals["date"] <= end)]
    return players, window


def _token_index(names: pd.Series) -> Dict[str, set]:
    """Name token -> Transfermarkt player ids: only players sharing a word with the name are scored."""
    idx: Dict[str, set] = {}
    for pid, name in names.items():
        for t in norm(name).split():
            if len(t) >= 3:
                idx.setdefault(t, set()).add(pid)
    return idx


def _candidates(idx: Dict[str, set], names: List[str]) -> set:
    out: set = set()
    for n in names:
        for t in norm(n).split():
            out |= idx.get(t, set())
    return out


def club_map(sb_players: pd.DataFrame, start: str = "2015-08-01", end: str = "2016-05-31", top: int = 8,
             min_votes: int = 3) -> Dict[str, str]:
    """StatsBomb team -> Transfermarkt club (name key). Club names differ between the sources ("Internazionale" /
    "Inter Milan", "Athletic Club" / "Athletic Bilbao"), so the club is found by its players: the team's
    regulars are matched by name and nationality, and each vote goes to the clubs that player was valued at
    during the season. (The club ids in the valuation table are not reliable - some rows carry the player's
    present-day club - so clubs are keyed by the name recorded with the valuation.)"""
    players, window = load_tm(start, end)
    meta = players.set_index("player_id")
    names = meta.loc[meta.index.intersection(window["player_id"].unique()), "name"]
    idx = _token_index(names)
    clubs_of = window.assign(club=window["current_club_name"].map(club_key)).groupby("player_id")["club"].agg(set)
    out: Dict[str, str] = {}
    for team, g in sb_players.groupby("team"):
        votes: Dict[str, int] = {}
        for p in g.nlargest(top, "minutes").itertuples():
            sb_names = [x for x in (p.nickname, p.player) if isinstance(x, str)]
            country = country_key(p.country)
            scored = []
            for pid in _candidates(idx, sb_names):
                sc = name_score(sb_names, names[pid])
                if country and country_key(meta.at[pid, "country_of_citizenship"]) == country:
                    sc += 0.08
                scored.append((sc, pid))
            if scored:
                sc, pid = max(scored)
                if sc >= 0.9:
                    for c in clubs_of[pid]:
                        votes[c] = votes.get(c, 0) + 1
        if votes:
            club, n = max(votes.items(), key=lambda kv: kv[1])
            if n >= min_votes:
                out[team] = club
    return out


def match_players(sb_players: pd.DataFrame, start: str = "2015-06-01", end: str = "2016-08-31",
                  threshold: float = 0.72, clubs: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """sb_players: player_id, player, nickname, country, team. Returns the input with tm_player_id, score, method.
    clubs: StatsBomb team -> Transfermarkt club key (see club_map); without it clubs are matched by name."""
    players, window = load_tm(start, end)
    window = window.assign(club=window["current_club_name"].map(club_key))
    meta = players.set_index("player_id")
    by_club: Dict[str, pd.Index] = {c: g["player_id"].unique() for c, g in window.groupby("club")}
    names = meta.loc[meta.index.intersection(window["player_id"].unique()), "name"]
    idx = _token_index(names)
    rows = []
    for p in sb_players.itertuples():
        names_p = [x for x in (p.nickname, p.player) if isinstance(x, str)]
        country = country_key(p.country)

        def best(ids, method):
            scored = []
            for pid in ids:
                if pid not in meta.index:
                    continue
                m = meta.loc[pid]
                s = name_score(names_p, m["name"])
                if country and country_key(m["country_of_citizenship"]) == country:
                    s += 0.08
                scored.append((s, pid))
            if not scored:
                return None
            scored.sort(reverse=True)
            top = scored[0]
            margin = top[0] - (scored[1][0] if len(scored) > 1 else 0)
            return {"tm_player_id": int(top[1]), "score": round(min(top[0], 1.08), 3), "margin": round(margin, 3),
                    "method": method}

        club = (clubs or {}).get(p.team, club_key(p.team))
        res = best(by_club.get(club, []), "club+name")
        if res is None or res["score"] < threshold:
            # moved during the season, or the club is unknown: search everyone valued in the window who shares
            # a name word, requiring a stronger name match and the same nationality
            cands = [pid for pid in _candidates(idx, names_p)
                     if country and country_key(meta.at[pid, "country_of_citizenship"]) == country]
            alt = best(cands, "name+country")
            if alt and alt["score"] >= threshold + 0.1 and (res is None or alt["score"] > res["score"]):
                res = alt
        if res is None or res["score"] < threshold:
            res = {"tm_player_id": None, "score": res["score"] if res else 0.0, "margin": None, "method": "unmatched"}
        rows.append({"player_id": p.player_id, "team": p.team, **res})
    out = sb_players.merge(pd.DataFrame(rows), on=["player_id", "team"], how="left")
    out["tm_name"] = out["tm_player_id"].map(players.set_index("player_id")["name"])
    return out


def value_at(tm_ids: pd.Series, date: str) -> pd.Series:
    """Last known market value on or before the date (EUR)."""
    vals = pd.read_csv(TM / "player_valuations.csv.gz", parse_dates=["date"])
    v = vals[vals["date"] <= date].sort_values("date").groupby("player_id")["market_value_in_eur"].last()
    return tm_ids.map(v)
