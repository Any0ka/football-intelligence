"""Step 6 of the study: was the method right? This is the only script that looks past the decision date.

It reads what scripts/find_candidates.py froze (shortlist, full candidate rankings, fair values) and compares
them with market values one and two years later and with what the club actually bought that summer.

python scripts/backtest.py Chelsea
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fi import events as fe, matching as mt, metrics as fm, pitchviz as pv, valuation as fv  # noqa: E402

HORIZONS = {"v2017": "2017-06-30", "v2018": "2018-06-30"}      # market value one and two years later
WINDOW = ("2016-06-01", "2016-09-01")          # the transfer window the decision was for
AGE_BANDS = [(0, 23.99, "до 24"), (24, 27.99, "24–27"), (28, 99, "28+")]


def main(team: str):
    slug = team.lower().replace(" ", "_")
    out = ROOT / "reports"
    fair = pd.read_parquet(fe.CACHE / "fair_values.parquet")
    short = pd.read_csv(out / f"{slug}_shortlist.csv")
    cands = pd.read_parquet(fe.CACHE / f"candidates_{slug}.parquet")
    for col, date in HORIZONS.items():
        fair[col] = fv.values_after(fair["tm_player_id"], date)
        fair[f"growth_{col}"] = np.log10(fair[col] / fair["value"])
    last = list(HORIZONS)[-1]
    g = f"growth_{last}"
    ok = fair.dropna(subset=[g])
    print(f"Игроков с оценкой летом 2016: {len(fair)}; с оценкой и в {HORIZONS[last][:4]}: {len(ok)} "
          f"(выбыли {len(fair) - len(ok)} — завершили карьеру или пропали из базы)")

    # ---- 1. does the gap predict growth? across everyone, and within age bands (young players grow anyway)
    rho, p = spearmanr(ok["gap"], ok[g])
    print(f"\nНедооценённость → рост стоимости за 2 года: Спирмен ρ = {rho:.2f} (p = {p:.1g}, n = {len(ok)})")
    for lo, hi, name in AGE_BANDS:
        b = ok[ok["age"].between(lo, hi)]
        r, pb = spearmanr(b["gap"], b[g])
        print(f"  возраст {name:6s}: ρ = {r:.2f} (p = {pb:.1g}, n = {len(b)})")
    ok = ok.assign(q=pd.qcut(ok["gap"], 5, labels=["1 — переоценены", "2", "3", "4", "5 — недооценены"]))
    by_q = ok.groupby("q", observed=True)[g].agg(["median", "size"])
    by_q["x"] = 10 ** by_q["median"]
    print("\nМедианный рост стоимости за 2 года по квинтилям недооценённости:")
    print(by_q[["x", "size"]].round(2).to_string())

    # ---- 2. the frozen shortlist: what happened to the recommended players
    short = short.merge(fair[["player_id", *HORIZONS]], on="player_id", how="left")
    tr = pd.read_csv(mt.TM / "transfers.csv.gz", parse_dates=["transfer_date"])
    moves = tr[(tr["transfer_date"] > fv.DECISION_DATE) & (tr["transfer_date"] <= "2018-09-01")]
    print("\nШорт-лист (зафиксирован до проверки) — стоимость тогда и потом:")
    for r in short.itertuples():
        later = " → ".join(money(getattr(r, col)) for col in HORIZONS)
        nxt = moves[moves["player_id"] == r.tm_player_id].sort_values("transfer_date")
        went = "; ".join(f"{m.transfer_date:%Y-%m} → {m.to_club_name}" + (f" (€{m.transfer_fee / 1e6:.0f} млн)" if m.transfer_fee and m.transfer_fee > 0 else "")
                         for m in nxt.itertuples())
        print(f"  {r.slot:4s} {r.rank}. {r.name:24s} {money(r.value)} → {later}   {went}")

    # ---- 2b. fair baselines: the filters alone already pick young, improving players
    cands[last] = fv.values_after(cands["tm_player_id"], HORIZONS[last])
    cands["growth"] = np.log10(cands[last] / cands["value"])
    c_ok = cands.dropna(subset=["growth"])
    young = ok[ok["age"] <= 29]
    groups = {
        "все игроки до 29 лет (≥900 мин)": young[g],
        "все кандидаты, прошедшие фильтры": c_ok["growth"],
        "топ-5 только по соответствию": c_ok.sort_values("fit", ascending=False).groupby("slot").head(5)["growth"],
        "топ-5 только по недооценённости": c_ok.sort_values("ratio", ascending=False).groupby("slot").head(5)["growth"],
        "топ-5 по TOPSIS (наш шорт-лист)": c_ok[c_ok["rank"] <= 5]["growth"],
    }
    print("\nС чем сравнивать шорт-лист (рост стоимости за 2 года):")
    base = []
    for name, gr in groups.items():
        base.append((name, 10 ** gr.median(), (gr > 0).mean(), len(gr)))
        print(f"  {name:36s} медиана ×{base[-1][1]:.2f}, подорожали {base[-1][2]:.0%} (n = {len(gr)})")

    # ---- 3. what the club really bought in that window, and where it stood in our rankings
    key = mt.club_key(team)
    buys = tr[(tr["transfer_date"] >= WINDOW[0]) & (tr["transfer_date"] <= WINDOW[1])
              & (tr["to_club_name"].map(mt.club_key) == key) & (tr["from_club_name"].map(mt.club_key) != key)]
    paid = buys[buys["transfer_fee"].fillna(0) > 0]
    other = buys[buys["transfer_fee"].fillna(0) <= 0]
    print(f"\nКого {team} купил летом 2016 на самом деле (платные трансферы; в таблице transfers есть не все сделки):")
    for b in paid.sort_values("transfer_fee", ascending=False).itertuples():
        f = fair[fair["tm_player_id"] == b.player_id]
        c = cands[cands["tm_player_id"] == b.player_id]
        where = (f"в нашем списке на {c['slot'].iloc[0]}: {int(c['rank'].iloc[0])}-й" if len(c)
                 else "в наших списках нет")
        info = (f"{fm.GROUP_NAMES[f['group'].iloc[0]]}, недооценённость ×{10 ** f['gap'].iloc[0]:.1f}" if len(f)
                else "не играл в открытых лигах 2015/16 ≥900 мин")
        fee = f"€{b.transfer_fee / 1e6:.1f} млн" if b.transfer_fee and b.transfer_fee > 0 else "без суммы/свободный"
        print(f"  {b.player_name:22s} из {b.from_club_name:22s} {fee:>14s} · {info} · {where}")
    if len(other):
        print("  без суммы (возвраты из аренды, свободные агенты): " + ", ".join(other["player_name"]))

    # ---- figure: growth by undervaluation quintile, and the shortlist against fair baselines
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.6), facecolor=pv.SURFACE,
                                   gridspec_kw={"width_ratios": [1, 1.15], "wspace": 0.3})
    bars(ax1, [str(q).replace(" — ", "\n") for q in by_q.index], by_q["x"], [f"n={n}" for n in by_q["size"]],
         f"Квинтили недооценённости лета 2016 (Спирмен ρ = {rho:.2f})", highlight=len(by_q) - 1)
    bars(ax2, [b[0].replace(" (", "\n(").replace("только ", "только\n").replace("прошедшие", "\nпрошедшие")
               .replace("до 29", "\nдо 29") for b in base], [b[1] for b in base],
         [f"подорожали\n{b[2]:.0%}, n={b[3]}" for b in base], "Шорт-лист против честных баз сравнения",
         highlight=len(base) - 1)
    fig.suptitle("Проверка временем: рост рыночной стоимости с лета 2016 по лето 2018 (медиана, ×)", x=0.04,
                 ha="left", fontsize=14, fontweight="bold", color=pv.INK)
    fig.text(0.04, 0.015, pv.SOURCE.replace("Premier League", "топ-5 лиг") + " · стоимости: transfermarkt-datasets (CC0)",
             fontsize=8, color=pv.MUTED)
    fig.subplots_adjust(left=0.04, right=0.99, top=0.84, bottom=0.24)
    path = out / "figures" / "backtest_value_growth.png"
    fig.savefig(path, dpi=200, facecolor=pv.SURFACE)
    print(f"\nкартинка: {path.relative_to(ROOT)}")


def bars(ax, labels, values, notes, title, highlight=None):
    """Bars from x1 (no change): up = grew, down = lost value; the highlighted bar in the series colour."""
    ax.set_facecolor(pv.SURFACE)
    xs = np.arange(len(values))
    colors = [pv.BLUE if i == highlight else "#a9c8f0" for i in xs]
    ax.bar(xs, np.array(values) - 1, bottom=1, color=colors, width=0.62)
    ax.axhline(1, color=pv.MUTED, lw=1)
    top = max(values)
    for x, v, note in zip(xs, values, notes):
        ax.text(x, max(v, 1) + top * 0.02, f"×{v:.2f}", ha="center", va="bottom", fontsize=11, fontweight="bold",
                color=pv.INK)
        ax.text(x, min(v, 1) - top * 0.02, note, ha="center", va="top", fontsize=8.2, color=pv.INK_2)
    ax.set_ylim(min(0.4, min(values) - 0.3), top * 1.15)
    ax.set_yticks([])
    ax.set_xticks(xs, labels, fontsize=8.6, color=pv.INK_2)
    ax.set_title(title, loc="left", fontsize=11, color=pv.INK, pad=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(colors=pv.INK_2, length=0)


def money(v):
    return "—" if pd.isna(v) else f"€{v / 1e6:.1f} млн"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else "Chelsea")
