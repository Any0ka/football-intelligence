"""Step 1 of the study: tactical diagnosis of one team against its league.

python scripts/diagnose_team.py "Chelsea"            -> reports/figures/<team>_*.png + printed tables
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fi import events as fe, metrics as fm, needs as fn, pitchviz as pv, shape as fs, tactics as ft  # noqa: E402

COMP, SEASON = "Premier League", "2015/2016"
SET_PIECES = {"From Corner", "From Free Kick"}          # throw-ins start too many ordinary possessions to count
MANAGERS_RU = {"Mourinho": "Моуринью", "Hiddink": "Хиддинк", "Holland": "Холланд"}


def main(team: str):
    out = ROOT / "reports" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    slug = team.lower().replace(" ", "_")
    matches, ev, spells = fe.season(COMP, SEASON)
    print(f"{COMP} {SEASON}: {len(matches)} матчей, {len(ev):,} событий, {spells['player_id'].nunique()} игроков")

    # ---- the team in the league
    tt = ft.league_table(matches, ev)
    r = tt.loc[team]
    print(f"\n{team}: {int(r.place)}-е место, {int(r.pts)} очков; xG {r.xg:.1f} / xGA {r.xga:.1f} "
          f"(разница xG — {int(r.xgd_rank)}-я в лиге, xGA — {int(r.xga_rank)}-я); голы {int(r.gf)}–{int(r.ga)}")
    print(tt[["place", "pts", "gf", "ga", "xg", "xga", "xgd", "xgd_rank"]].round(1).to_string())

    # ---- positions: who played each slot of the main formation and how good he was against a benchmark
    table = fm.player_table(ev, spells)
    top6 = list(tt.index[:6])
    formation = "4231"
    layout = pv._pitch().get_formation(formation)
    pd.set_option("display.width", 220)
    panels = []
    for label, heading, pool in (("к игрокам всей лиги", "Эталон — вся лига", None),
                                 ("к игрокам топ-6", "Эталон — топ-6", top6)):
        pct = fm.percentiles(table, pool_teams=pool)
        slots, detail = fn.position_slots(spells, pct, team, layout, fs.slot_of(formation))
        panels.append((heading, slots))
        print(f"\nСила позиций {label} (процентиль среди игроков той же роли с ≥900 мин; 50 = медиана эталона):")
        for pos, s in zip(layout, slots):
            score = "—" if s["score"] is None else f"{s['score']:.0f}"
            print(f"  {pos.name:4s} {score:>4}  " + ", ".join(f"{n} {m:.0f}′" for n, m in s["players"][:3]))
    print(f"\nтоп-6: {', '.join(top6)}")
    print("\nПоказатели игроков по позициям относительно топ-6 (процентили; 'обыграли' и 'потери' инвертированы):")
    labels = {f"pct_{m}": label[:28] for m, (label, _) in fm.METRICS.items()}
    print(detail.drop(columns="player_id").rename(columns=labels).to_string(index=False))
    pv.formation_strength(
        formation, panels,
        title=f"{pv.ru(team)} 2015/16: сила позиций в схеме 4-2-3-1",
        subtitle=("Число в круге — средний процентиль игроков этой позиции среди игроков той же роли (≥900 мин), взвешенный по минутам.\n"
                  "Слева эталон — вся лига, справа — игроки топ-6: уровень, с которым соревнуется претендент на титул."),
        path=str(out / f"{slug}_positions.png"))

    # ---- where the team concedes
    shots = ev[ev["type"] == "Shot"]
    against_ids = matches[(matches["home"] == team) | (matches["away"] == team)]["match_id"]
    against = shots[shots["match_id"].isin(against_ids) & (shots["team"] != team)]
    league_zone = pv.zone_sum(shots["x"], shots["y"], shots["shot_xg"].fillna(0)) / (2 * len(matches))
    n = int(r.matches)
    sp_share = against[against["play_pattern"].isin(SET_PIECES)]["shot_xg"].sum() / against["shot_xg"].sum()
    league_sp = shots[shots["play_pattern"].isin(SET_PIECES)]["shot_xg"].sum() / shots["shot_xg"].sum()
    kpis = [f"xGA за матч: {r.xga / n:.2f} (лига в среднем {shots['shot_xg'].sum() / (2 * len(matches)):.2f})",
            f"пропущено {int(r.ga)} при xGA {r.xga:.1f}",
            f"после угловых и штрафных {sp_share:.0%} xGA (лига {league_sp:.0%})"]
    print("\n" + " | ".join(kpis))
    pv.conceded(against, n, league_zone,
                title=f"{pv.ru(team)} 2015/16: откуда пропускаем",
                subtitle=("Соперники атакуют вверх, в наши ворота. Левая сторона картинки — левый фланг соперника,\n"
                          "то есть наш правый (сторона правого защитника). Зоны построены по разметке штрафной."),
                path=str(out / f"{slug}_conceded.png"), kpis=kpis)
    # ---- by manager: how the formation actually looked, and goals against xG (execution and luck)
    tm = matches[(matches["home"] == team) | (matches["away"] == team)].copy()
    tm["manager"] = [r.home_manager if r.home == team else r.away_manager for r in tm.itertuples()]
    tm["gf"] = [r.home_score if r.home == team else r.away_score for r in tm.itertuples()]
    tm["ga"] = [r.away_score if r.home == team else r.home_score for r in tm.itertuples()]
    tm["pts"] = [3 if f > a else 1 if f == a else 0 for f, a in zip(tm["gf"], tm["ga"])]
    team_shots = shots[shots["match_id"].isin(tm["match_id"])]
    xg = team_shots.groupby(["match_id", team_shots["team"] == team])["shot_xg"].sum().unstack(fill_value=0)
    tm["xg"], tm["xga"] = tm["match_id"].map(xg[True]), tm["match_id"].map(xg[False])
    by = tm.groupby("manager", sort=False).agg(matches=("pts", "size"), ppg=("pts", "mean"), gf=("gf", "sum"),
                                               xg=("xg", "sum"), ga=("ga", "sum"), xga=("xga", "sum"))
    by["finishing"], by["conceding"] = by["gf"] - by["xg"], by["ga"] - by["xga"]
    print("\nПо тренерам (голы против ожидаемых):")
    print(by.round(2).to_string())
    panels = []
    for mgr, part in tm.groupby("manager", sort=False):
        if len(part) < 5:
            continue
        nodes, edges = ft.pass_network(ev, spells, team, part["match_id"])
        st = ft.style(ev, team, part["match_id"])
        first, last = part["date"].min(), part["date"].max()
        surname = MANAGERS_RU.get(mgr.split()[-1], mgr.split()[-1]) if mgr else "?"
        heading = f"{surname} ({first:%m.%Y} – {last:%m.%Y})"
        line = (f"{len(part)} матчей · {part['pts'].mean():.2f} очка за матч · xG {part['xg'].mean():.2f} – "
                f"xGA {part['xga'].mean():.2f} · владение {st['possession']:.0%} · PPDA {st['ppda']:.1f}")
        panels.append((heading, nodes, edges, line))
    if panels:
        pv.pass_networks(
            panels, f"{pv.ru(team)} 2015/16: как на самом деле выглядела схема при разных тренерах",
            "Кружок — позиция в схеме: средняя точка, где игроки этой позиции отдают и принимают передачи; под ним — основной игрок.\n"
            "Линия — точные передачи между позициями (≥2 за матч), толще — чаще. Только время до первой замены.",
            str(out / f"{slug}_pass_network.png"))
    print("\nкартинки:", *sorted(str(p.relative_to(ROOT)) for p in out.glob(f"{slug}_*.png")), sep="\n  ")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else "Chelsea")
