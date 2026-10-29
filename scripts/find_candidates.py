"""Steps 2-5 of the study: needs of the team -> candidates in the top five leagues -> fair value -> shortlist.

python scripts/find_candidates.py Chelsea [budget in millions EUR]

Uses only what was known in the summer of 2016 (events of 2015/16, market values up to 30.06.2016).
The shortlist is written to reports/ before anything about later seasons is looked at (scripts/backtest.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fi import (decision as fd, events as fe, metrics as fm, needs as fn, pitchviz as pv,  # noqa: E402
                pool as fp, shape as fs, tactics as ft, valuation as fv)

COMP = "Premier League"
FORMATION = "4231"


def main(team: str, budget: float):
    out = ROOT / "reports"
    figs = out / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    slug = team.lower().replace(" ", "_")
    pd.set_option("display.width", 220)

    # ---- the pool: every player of the five leagues, linked to market values
    leagues = [c for c in fp.LEAGUES if fp.downloaded(c)]
    players, teams = fp.load(leagues)
    links = pd.concat([fp.links(c) for c in leagues], ignore_index=True)
    by_league = players.groupby("league").agg(teams=("team", "nunique"), players=("player_id", "nunique"))
    print("Пул кандидатов (сезон 2015/16):\n" + by_league.to_string())
    mins = links.groupby("league").apply(lambda g: g.loc[g["tm_player_id"].notna(), "minutes"].sum() / g["minutes"].sum(),
                                         include_groups=False)
    print("Сопоставлено с Transfermarkt, доля минут:", ", ".join(f"{k} {v:.1%}" for k, v in mins.items()))

    keys = ["player_id", "team"]
    europe = fm.percentiles(players)                       # benchmark: every regular of the five leagues
    europe = europe.merge(links[keys + ["tm_player_id", "tm_name", "value", "value_date", "stale", "age"]],
                          on=keys, how="left")

    # ---- fair value: what the market pays for players like this one (out-of-fold)
    rows = fv.player_rows(europe)
    train = rows[rows["value"].notna() & ~rows["stale"] & rows["age"].notna() & (rows["minutes"] >= fm.MIN_MINUTES)]
    valued, report = fv.fit_fair_value(train)
    print(f"\nМодель справедливой стоимости: {report['n']} игроков с ≥900 мин; "
          + "; ".join(f"{k}: R² {v['r2']:.2f}, типичная ошибка ×{v['median_x']:.2f}"
                      for k, v in report.items() if isinstance(v, dict))
          + f" → выбрана {report['chosen']}")
    gap = valued.set_index("player_id")[["fair_value", "gap", "ratio"]]
    europe = europe.join(gap, on="player_id")

    # ---- needs of the team: slots below the top six or with an ageing main player
    matches, ev, spells = fe.season(COMP, fp.SEASON)
    tt = ft.league_table(matches, ev)
    top6 = list(tt.index[:6])
    table = fm.player_table(ev, spells)
    layout = pv._pitch().get_formation(FORMATION)
    slots, detail = fn.position_slots(spells, fm.percentiles(table, pool_teams=top6), team, layout, fs.slot_of(FORMATION))
    mine = links[links["team"] == team].set_index("player_id")
    needs = fn.needs(layout, slots, detail, mine["age"].dropna().to_dict())
    print("\nПотребности (сила позиции к топ-6, основной игрок, возраст летом 2016):")
    for r in needs.itertuples():
        mark = "НУЖЕН" if r.need else "     "
        age = "—" if pd.isna(r.main_age) else f"{r.main_age:.0f}"
        print(f"  {mark} {r.slot:4s} {r.score:5.1f}  {r.main} ({age})  {r.reason}")

    # ---- candidates per needed slot
    _, slot_europe = fn.position_slots(spells, europe[europe["league"] == COMP], team, layout, fs.slot_of(FORMATION))
    ranked, funnels, stab = {}, {}, {}
    for need in needs[needs["need"]].itertuples(index=False):
        need = pd.Series(need._asdict())
        inc = slot_europe[(slot_europe["slot"] == need.slot) & (slot_europe["group"] == need.group)]
        inc_fit = float((fd.fit_score(inc, need.weights) * inc["slot_minutes"]).sum() / inc["slot_minutes"].sum())
        need["incumbent_fit"] = inc_fit
        needs.loc[needs["slot"] == need.slot, "incumbent_fit"] = inc_fit
        c, funnel = fd.candidates(europe, need, team, inc_fit)
        r = fd.rank(c)
        r["stability"] = fd.stability(r)
        ranked[need.slot], funnels[need.slot] = r, funnel
        print(f"\n{need.slot}: нужен {fm.GROUP_NAMES[need.group]}{' (' + need.side + ')' if need.side else ''}; "
              f"сейчас {need.main}, соответствие {inc_fit:.0f}. Веса показателей: "
              + ", ".join(f"{fm.METRICS[m][0].split(' (')[0]} {w:.0%}" for m, w in need.weights.items()))
        print("  отбор: " + " → ".join(f"{k} {v}" for k, v in funnel.items()))
        cols = ["name", "team", "league", "age", "value", "fair_value", "ratio", "fit", "role_minutes", "score",
                "stability"]
        show = r.head(8)
        print(show.assign(value=show["value"] / 1e6, fair_value=show["fair_value"] / 1e6)[cols]
              .round(2).to_string(index=False))

    # ---- one player per slot within the budget
    plans = {}
    for b in sorted({budget, 60e6, 120e6, 200e6}):
        plan = fd.budget_plan(ranked, b)
        plans[b] = plan
        spent = sum(ranked[s].at[i, "value"] for s, i in plan)
        print(f"\nБюджет €{b / 1e6:.0f} млн: " + "; ".join(
            f"{s} — {ranked[s].at[i, 'name']} ({ranked[s].at[i, 'team']}, €{ranked[s].at[i, 'value'] / 1e6:.1f} млн)"
            for s, i in plan) + f"  | итого €{spent / 1e6:.1f} млн")

    # ---- frozen output: the backtest reads these files and nothing else from this step
    short = pd.concat([r.head(5).assign(slot=s, rank=range(1, min(5, len(r)) + 1)) for s, r in ranked.items()])
    short = short[["slot", "rank", "player_id", "tm_player_id", "name", "team", "league", "age", "value", "fair_value",
                   "ratio", "fit", "role_minutes", "score", "stability"]]
    short.to_csv(out / f"{slug}_shortlist.csv", index=False)
    valued.drop(columns=[c for c in valued.columns if c.startswith("pct_")]).to_parquet(fe.CACHE / "fair_values.parquet")
    full = pd.concat([r.assign(slot=s, rank=range(1, len(r) + 1)) for s, r in ranked.items()])
    full[[c for c in short.columns if c in full.columns]].to_parquet(fe.CACHE / f"candidates_{slug}.parquet")
    plan = plans[budget]
    (out / f"{slug}_plan.json").write_text(json.dumps({
        "decision_date": fv.DECISION_DATE, "budget_eur": budget, "criteria": fd.CRITERIA,
        "rules": {"max_age": fd.MAX_AGE, "max_price": fd.MAX_PRICE, "side_share": fd.SIDE_SHARE},
        "value_model": report,
        "needs": [{"slot": r.slot, "group": r.group, "score": r.score, "main": r.main, "main_age": r.main_age,
                   "reason": r.reason, "weights": r.weights, "incumbent_fit": r.incumbent_fit}
                  for r in needs[needs["need"]].itertuples()],
        "plan": [{"slot": s, "player": ranked[s].at[i, "name"], "team": ranked[s].at[i, "team"],
                  "tm_player_id": int(ranked[s].at[i, "tm_player_id"]), "value": float(ranked[s].at[i, "value"])}
                 for s, i in plan],
    }, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"\nзафиксировано: reports/{slug}_shortlist.csv, reports/{slug}_plan.json")
    return needs, ranked, plans, europe, valued, slots


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else "Chelsea", float(sys.argv[2]) * 1e6 if len(sys.argv) > 2 else 120e6)
