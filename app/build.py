"""Builds the data of the web app with the fi package: one JSON per league (clubs, players, shapes, pass
networks, conceded shots, needs), the candidate pool with fair values, and the shape models.

python -m app.build          -> app/web/data/*.json for every league whose matches are downloaded

The page itself only reads these files, so it can be served by any static server (or GitHub Pages).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fi import (decision as fd, events as fe, finance as ff, metrics as fm, needs as fn, pitchviz as pv,  # noqa: E402
                pool as fp, shape as fs, tactics as ft, valuation as fv)

OUT = ROOT / "app" / "web" / "data"
GRID = (12, 8)                  # touch map: 10 x 10 yard cells
MIN_GROUP_MINUTES = 90          # a group row below this is not shown on the player card
MANAGER_MATCHES = 5
FIN_SEASONS = range(2013, 2018)  # squad return 2013/14 .. 2017/18: three seasons before the decision, two after


def r(v, nd=2):
    """Round for JSON; NaN and None become null."""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    if isinstance(v, (np.floating, float)):
        return round(float(v), nd)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def clean(o):
    """NaN / inf anywhere in the structure -> null: JSON has no NaN, and one NaN makes the browser reject the
    whole file (a La Liga player without a nationality once broke the league)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):          # np.float64 is a float too
        return None
    return o


def write(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                            encoding="utf-8")


def slug(name: str) -> str:
    return fp._tag(name)


def player_cards(team: str, table: pd.DataFrame, pcts: dict, europe: pd.DataFrame, links: pd.DataFrame,
                 ev: pd.DataFrame) -> list:
    """Every player of the club: per-90 numbers per position group, percentiles against three benchmarks,
    market value and fair value, his photo, a touch map and his shots."""
    mine = table[(table["team"] == team) & (table["minutes"] >= MIN_GROUP_MINUTES)]
    lk = links[links["team"] == team].set_index("player_id")
    eu = europe[europe["team"] == team].set_index(["player_id", "group"])
    own = ev[(ev["team"] == team) & ev["x"].notna() & ev["player_id"].notna() & ~ev["type"].isin(fs.TACTICS)]
    shots = own[own["type"] == "Shot"]
    cards = []
    for pid, rows in mine.groupby("player_id"):
        pid = int(pid)
        groups = {}
        for row in rows.sort_values("minutes", ascending=False).itertuples():
            g = row.group
            entry = {"minutes": r(row.minutes, 0),
                     "per90": {m: r(getattr(row, m), 3) for m in fm.ROLE_METRICS[g]}}
            for bench, pct in pcts.items():
                p = pct[(pct["player_id"] == pid) & (pct["team"] == team) & (pct["group"] == g)]
                if len(p):
                    entry[bench] = {m: r(p[f"pct_{m}"].iloc[0], 0) for m in fm.ROLE_METRICS[g]}
                    entry[f"score_{bench}"] = r(p["role_score"].iloc[0], 1)
            if (pid, g) in eu.index:
                e = eu.loc[(pid, g)]
                entry["europe"] = {m: r(e[f"pct_{m}"], 0) for m in fm.ROLE_METRICS[g]}
                entry["score_europe"] = r(e["role_score"], 1)
            groups[g] = entry
        mine_ev = own[own["player_id"] == pid]
        h, _, _ = np.histogram2d(mine_ev["x"], mine_ev["y"], bins=GRID, range=[[0, 120], [0, 80]])
        h = h / h.max() if h.max() > 0 else h
        s = shots[shots["player_id"] == pid]
        info = lk.loc[pid] if pid in lk.index else None
        if isinstance(info, pd.DataFrame):
            info = info.iloc[0]
        cards.append({
            "id": pid, "name": rows["name"].iloc[0], "full_name": rows["player"].iloc[0],
            "country": None if info is None else info.get("country"),
            "minutes": r(rows["minutes"].sum(), 0), "groups": groups,
            "tm_id": None if info is None or pd.isna(info["tm_player_id"]) else int(info["tm_player_id"]),
            "photo": None if info is None or pd.isna(info["photo"]) else info["photo"],
            "age": None if info is None else r(info["age"], 1),
            "value": None if info is None else r(info["value"], 0),
            "value_date": None if info is None or pd.isna(info["value_date"]) else str(info["value_date"].date()),
            "grid": [[r(v, 2) for v in col] for col in h],
            "shots": [[r(a.x, 1), r(a.y, 1), r(a.shot_xg, 3), int(a.outcome == "Goal")] for a in s.itertuples()],
        })
    return cards


def shot_map(s: pd.DataFrame, n: int, league_zone: np.ndarray) -> dict:
    """One side's shots over the season (each in the shooting team's frame): every shot, xG per match by zone
    minus the league average for one team, and the share of xG after corners and free kicks."""
    zone = pv.zone_sum(s["x"], s["y"], s["shot_xg"].fillna(0)) / n
    sp = s[s["play_pattern"].isin({"From Corner", "From Free Kick"})]["shot_xg"].sum() / max(1e-9, s["shot_xg"].sum())
    return {"shots": [[r(a.x, 1), r(a.y, 1), r(a.shot_xg, 3), int(a.outcome == "Goal")] for a in s.itertuples()],
            "zone_diff": [[r(v, 3) for v in row_] for row_ in (zone - league_zone)],
            "xg_pm": r(s["shot_xg"].sum() / n, 2), "set_piece_share": r(sp, 3)}


def finance(fin: pd.DataFrame, stayed: pd.DataFrame, club_id, names: pd.Series) -> dict:
    """Squad return per season for one club, with the league median and the players who moved it most.
    stayed: players who stayed, with both values, of the shown seasons."""
    if club_id is None:
        return {"seasons": []}
    mine = stayed[stayed["club_id"] == club_id]
    rows = []
    for f in fin[(fin["club_id"] == club_id) & fin["season"].isin(FIN_SEASONS)].sort_values("season").itertuples():
        st = mine[mine["season"] == f.season].assign(d=lambda d: d["value"] - d["value_prev"]).sort_values("d")
        rows.append({"season": int(f.season), "label": f"{f.season}/{(f.season + 1) % 100:02d}",
                     "squad": count(f.squad), "value": r(f.squad_value, 0), "ret": r(f.ret, 4),
                     "stayed": count(f.stayed), "v0": r(f.v0, 0), "v1": r(f.v1, 0),
                     "joined": count(f.joined), "joined_value": r(f.joined_value, 0),
                     "left": count(f.left), "left_value": r(f.left_value, 0),
                     "median": r(f.median, 4), "rank": count(f.rank), "of": count(f.of),
                     "up": movers(st[st["d"] > 0].iloc[::-1].head(3), names),
                     "down": movers(st[st["d"] < 0].head(3), names)})
    return {"club_id": int(club_id), "seasons": rows}


def count(v):
    return None if pd.isna(v) else int(v)


def movers(part: pd.DataFrame, names: pd.Series) -> list:
    return [[names.get(p.player_id, str(p.player_id)), r(p.value_prev, 0), r(p.value, 0)] for p in part.itertuples()]


def club_data(team, league, matches, ev, spells, tt, top6, table, pcts, europe, links, shapes, league_zone):
    formation, share = fs.main_formation(shapes, team)
    layout = fs.layout(formation)
    slot_ids = fs.slot_of(formation)
    ages = links[links["team"] == team].set_index("player_id")["age"].dropna().to_dict()
    slots6, detail6 = fn.position_slots(spells, pcts["top6"], team, layout, slot_ids)
    slots_l, _ = fn.position_slots(spells, pcts["league"], team, layout, slot_ids)
    _, detail_eu = fn.position_slots(spells, europe[europe["league"] == league], team, layout, slot_ids)
    needs = fn.needs(layout, slots6, detail6, ages).set_index("slot")

    slot_rows = []
    for i, (pos, s6, sl) in enumerate(zip(layout, slots6, slots_l)):
        primary = fs.POSITION_NAMES[pos.statsbomb[0]]
        group = fm.GROUP_OF[primary]
        n = needs.loc[pos.name] if pos.name in needs.index else None
        weights = n["weights"] if n is not None and n["group"] == group else \
            {m: 1 / len(fm.ROLE_METRICS[group]) for m in fm.ROLE_METRICS[group]}
        inc = detail_eu[(detail_eu["slot"] == pos.name) & (detail_eu["group"] == group)]
        inc_fit = (float((fd.fit_score(inc, weights) * inc["slot_minutes"]).sum() / inc["slot_minutes"].sum())
                   if len(inc) else None)
        played = spells[(spells["team"] == team) & (spells["position_id"].map(slot_ids) == i)]
        by_player = played.groupby("player_id")["minutes"].sum().sort_values(ascending=False)
        slot_rows.append({
            "i": i, "code": pos.name, "group": group, "side": fn.slot_side(pos.name, group),
            "tx": r(pos.x, 1), "ty": r(pos.y, 1),
            "score_top6": r(s6["score"], 1), "score_league": r(sl["score"], 1),
            "need": bool(n["need"]) if n is not None else False, "reason": n["reason"] if n is not None else "",
            "weights": {m: r(w, 3) for m, w in weights.items()}, "incumbent_fit": r(inc_fit, 1),
            "players": [[int(p), r(m, 0)] for p, m in by_player.items() if m >= 1],
        })

    row = tt.loc[team]
    tm_matches = matches[(matches["home"] == team) | (matches["away"] == team)].copy()
    tm_matches["manager"] = [m.home_manager if m.home == team else m.away_manager for m in tm_matches.itertuples()]
    tm_matches["gf"] = [m.home_score if m.home == team else m.away_score for m in tm_matches.itertuples()]
    tm_matches["ga"] = [m.away_score if m.home == team else m.home_score for m in tm_matches.itertuples()]
    tm_matches["pts"] = [3 if f > a else 1 if f == a else 0 for f, a in zip(tm_matches["gf"], tm_matches["ga"])]
    shots = ev[ev["type"] == "Shot"]
    team_shots = shots[shots["match_id"].isin(tm_matches["match_id"])]
    xg = team_shots.groupby(["match_id", team_shots["team"] == team])["shot_xg"].sum().unstack(fill_value=0)
    tm_matches["xg"] = tm_matches["match_id"].map(xg.get(True, pd.Series(dtype=float))).fillna(0)
    tm_matches["xga"] = tm_matches["match_id"].map(xg.get(False, pd.Series(dtype=float))).fillna(0)

    canonical = {fs.POSITION_NAMES[pid]: fs.POSITION_NAMES[layout[s].statsbomb[0]] for pid, s in slot_ids.items()}
    slot_of_name = {fs.POSITION_NAMES[pos.statsbomb[0]]: i for i, pos in enumerate(layout)}
    managers = []
    for mgr, part in tm_matches.groupby("manager", sort=False):
        entry = {"name": mgr or "?", "matches": int(len(part)), "ppg": r(part["pts"].mean()),
                 "gf": int(part["gf"].sum()), "ga": int(part["ga"].sum()),
                 "xg": r(part["xg"].sum(), 1), "xga": r(part["xga"].sum(), 1),
                 "from": str(part["date"].min().date()), "to": str(part["date"].max().date())}
        if len(part) >= MANAGER_MATCHES:
            nodes, edges = ft.pass_network(ev, spells, team, part["match_id"], canonical=canonical)
            st = ft.style(ev, team, part["match_id"])
            entry["style"] = {k: r(v, 3) for k, v in st.items()}
            entry["nodes"] = [{"slot": slot_of_name.get(p), "code": nd.code, "x": r(nd.x, 1), "y": r(nd.y, 1),
                               "per_match": r(nd.per_match, 1), "label": nd.label} for p, nd in nodes.iterrows()]
            entry["edges"] = [{"a": slot_of_name.get(e.a), "b": slot_of_name.get(e.b), "per_match": r(e.per_match, 1)}
                              for e in edges.itertuples()]
        managers.append(entry)

    played = shots["match_id"].isin(tm_matches["match_id"])
    n = int(row.matches)
    st = ft.style(ev, team, tm_matches["match_id"])
    return {
        "team": team, "league": league,
        "summary": {"place": int(row.place), "matches": n, "pts": int(row.pts), "gf": int(row.gf), "ga": int(row.ga),
                    "xg": r(row.xg, 1), "xga": r(row.xga, 1), "xgd_rank": int(row.xgd_rank),
                    "xga_rank": int(row.xga_rank), "top6": team in top6,
                    **{k: r(v, 3) for k, v in st.items()}},
        "formation": formation, "formation_share": r(share, 2),
        "slots": slot_rows,
        "managers": managers,
        "scored": shot_map(shots[played & (shots["team"] == team)], n, league_zone),
        "conceded": shot_map(shots[played & (shots["team"] != team)], n, league_zone),
        "players": player_cards(team, table, pcts, europe, links, ev),
        "names": {int(k): v for k, v in spells[spells["team"] == team].assign(
            n=lambda d: d["nickname"].fillna(d["player"])).groupby("player_id")["n"].first().items()},
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    leagues = [c for c in fp.LEAGUES if fp.downloaded(c)]
    print("лиги:", ", ".join(leagues), flush=True)
    players, teams = fp.load(leagues)
    links = pd.concat([fp.links(c) for c in leagues], ignore_index=True)
    links["photo"] = fv.photos(links["tm_player_id"])       # not in the cached links: older caches get it too
    keys = ["player_id", "team"]
    europe = fm.percentiles(players).merge(
        links[keys + ["tm_player_id", "value", "value_date", "stale", "age"]], on=keys, how="left")

    rows = fv.player_rows(europe)
    train = rows[rows["value"].notna() & ~rows["stale"].astype(bool) & rows["age"].notna()
                 & (rows["minutes"] >= fm.MIN_MINUTES)]
    valued, report = fv.fit_fair_value(train)
    print(f"модель стоимости: {report}", flush=True)
    europe = europe.join(valued.set_index("player_id")[["fair_value", "gap", "ratio"]], on="player_id")

    # squad return by market value, for every club and season of the data (the league median needs all clubs)
    ap = ff.appearances()
    mv = ff.moves(ff.squads(ap), ff.season_values())
    fin = ff.with_league(ff.returns(mv), ap, fp.LEAGUES.values())
    stayed = mv[mv["season"].isin(FIN_SEASONS) & (mv["status"] == "stayed")].dropna(subset=["value", "value_prev"])
    names = ff.player_names()

    clubs, shapes_all, index_leagues, locations = {}, [], [], []
    for league in leagues:
        t = time.time()
        matches, ev, spells = fe.season(league, fp.SEASON)
        if "formation" not in ev.columns:          # cache from before formations were kept
            matches, ev, spells = fe.season(league, fp.SEASON, refresh=True)
        shapes = fs.match_shapes(ev, spells)
        shapes_all.append(shapes)
        on_ball = ev[ev["x"].notna() & ev["player_id"].notna() & ~ev["type"].isin(fs.TACTICS)]
        locations.append(on_ball.assign(group=on_ball["position"].map(fm.GROUP_OF))
                         .groupby(["player_id", "team", "group"])[["x", "y"]].mean())
        tt = ft.league_table(matches, ev)
        full = tt[tt["matches"] >= fp.FULL_SEASON]
        if len(full) < 10:                          # Bundesliga: only Leverkusen is open - candidates only
            print(f"{league}: только кандидаты ({len(full)} команда с полным сезоном)", flush=True)
            continue
        top6 = list(full.index[:6])
        table = players[players["league"] == league]
        pcts = {"league": fm.percentiles(table), "top6": fm.percentiles(table, pool_teams=top6)}
        shots = ev[ev["type"] == "Shot"]
        league_zone = pv.zone_sum(shots["x"], shots["y"], shots["shot_xg"].fillna(0)) / (2 * len(matches))
        clubs[league] = {team: club_data(team, league, matches, ev, spells, tt, top6, table, pcts, europe, links,
                                         shapes, league_zone) for team in full.index}
        ids = ff.club_ids(links[links["league"] == league], ap, fp.LEAGUES[league])
        for team, c in clubs[league].items():
            c["finance"] = finance(fin, stayed, ids.get(team), names)
        index_leagues.append({"name": league, "ru": fp.LEAGUE_RU[league], "file": f"league_{slug(league)}.json",
                              "top6": top6,
                              "clubs": [{"team": tm, "place": int(full.loc[tm, "place"]),
                                         "pts": int(full.loc[tm, "pts"])} for tm in full.index]})
        print(f"{league}: {len(full)} клубов, {time.time() - t:.0f} с", flush=True)
        del ev

    # shape models: spread pooled over every team of every league playing the formation
    shapes = pd.concat(shapes_all, ignore_index=True)
    models = {}
    for league, cs in clubs.items():
        for team, c in cs.items():
            f = c["formation"]
            if f not in models:
                try:
                    models[f] = fs.model(shapes, f)
                except (ValueError, np.linalg.LinAlgError):      # too few complete matches in a rare formation
                    models[f] = None
                    print(f"  схема {f}: мало данных для модели формы — игроков можно только показать", flush=True)
            # the team's own average shape in its formation (whether or not the model could be fitted)
            own = shapes[(shapes["team"] == team) & (shapes["formation"] == f)]
            mean = own.groupby("slot")[["x", "y"]].mean()
            for s in c["slots"]:
                x, y = (mean.loc[s["i"]] if s["i"] in mean.index else (s["tx"], s["ty"]))
                s["x"], s["y"] = r(x, 1), r(y, 1)
        write(f"league_{slug(league)}.json", {"league": league, "clubs": cs})

    # the candidate pool: every regular (>=900 min in the group) of the five leagues
    pool = europe[europe["reliable"]].join(pd.concat(locations).rename(columns={"x": "ax", "y": "ay"}),
                                           on=["player_id", "team", "group"])
    # what happened next - shown only behind the "что было дальше" switch, never used by the ranking
    pool = pool.assign(v2017=fv.values_after(pool["tm_player_id"], "2017-06-30"),
                       v2018=fv.values_after(pool["tm_player_id"], "2018-06-30"))
    pool_rows = []
    for p in pool.itertuples():
        pool_rows.append({
            "id": int(p.player_id), "name": p.name, "team": p.team, "league": p.league, "group": p.group,
            "minutes": r(p.minutes, 0), "age": r(p.age, 1), "value": r(p.value, 0),
            "fresh": bool(pd.notna(p.value) and not p.stale), "fair": r(p.fair_value, 0), "gap": r(p.gap, 3),
            "right": r(p.right_share, 2), "left": r(p.left_share, 2), "score": r(p.role_score, 1),
            "pct": {m: r(getattr(p, f"pct_{m}"), 0) for m in fm.ROLE_METRICS[p.group]},
            "team_place": int(p.team_place), "team_league": fp.LEAGUE_RU[p.league],
            "ax": r(p.ax, 1), "ay": r(p.ay, 1),             # where his actions are on average (own attacking frame)
            "v2017": r(p.v2017, 0), "v2018": r(p.v2018, 0),
        })
    write("pool.json", pool_rows)

    index = {
        "season": "2015/16", "decision_date": fv.DECISION_DATE, "decision_season": 2015, "leagues": index_leagues,
        "candidate_leagues": [{"name": c, "ru": fp.LEAGUE_RU[c]} for c in leagues],
        "metrics": {m: {"label": lab, "higher": hib} for m, (lab, hib) in fm.METRICS.items()},
        "role_metrics": fm.ROLE_METRICS, "groups": fm.GROUP_NAMES,
        "criteria": {k: {"weight": w, "benefit": b, "label": fd.CRITERIA_RU[k]} for k, (w, b) in fd.CRITERIA.items()},
        "rules": {"max_age": fd.MAX_AGE, "max_price": fd.MAX_PRICE, "side_share": fd.SIDE_SHARE,
                  "weak": fn.WEAK, "old": fn.OLD, "min_minutes": fm.MIN_MINUTES},
        "value_model": report,
        "shape_models": {f: {"parts": m["parts"], "teams": m["teams"],
                             "cov": [[r(v, 3) for v in row_] for row_ in m["cov"]],
                             "sd": [[r(v, 1) for v in row_] for row_ in m["sd"]]} for f, m in models.items() if m},
        "zones": {"x": pv.X_EDGES, "y": pv.Y_EDGES},
    }
    write("index.json", index)
    for f in sorted(OUT.glob("*.json")):
        print(f"  {f.name}: {f.stat().st_size / 1e6:.2f} МБ")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
