"""Top-down pitch pictures: formation with position strength, pass networks, where goals are conceded.

Colour rules: one diverging scale for "worse / better than the benchmark" (red - grey - blue, grey is
the benchmark median), size for magnitude, text in ink colours, never in data colours. Every picture
names its data source (StatsBomb licence).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.patches import Rectangle
from mplsoccer import VerticalPitch

matplotlib.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

INK, INK_2, MUTED, LINE, SURFACE = "#0b0b0b", "#52514e", "#898781", "#c9c8c0", "#fcfcfb"
BLUE, RED, NEUTRAL = "#2a78d6", "#e34948", "#f0efec"
DIVERGING = LinearSegmentedColormap.from_list("weak_strong", ["#b3261e", RED, "#f3b8b3", NEUTRAL, "#a9c8f0", BLUE, "#184f95"])
SOURCE = "Данные: StatsBomb Open Data · Premier League 2015/16"
TEAM_RU = {"Chelsea": "Челси", "Arsenal": "Арсенал", "Leicester City": "Лестер", "Tottenham Hotspur": "Тоттенхэм",
           "Manchester City": "Манчестер Сити", "Manchester United": "Манчестер Юнайтед", "Liverpool": "Ливерпуль",
           "Southampton": "Саутгемптон", "West Ham United": "Вест Хэм", "Everton": "Эвертон",
           "Aston Villa": "Астон Вилла", "Newcastle United": "Ньюкасл"}


def ru(team: str) -> str:
    return TEAM_RU.get(team, team)


def _pitch(half: bool = False) -> VerticalPitch:
    return VerticalPitch(pitch_type="statsbomb", half=half, pitch_color=SURFACE, line_color=LINE,
                         linewidth=1.2, goal_type="box", pad_bottom=2 if half else 0.5)


def _canvas(pitch: VerticalPitch, ncols: int, figheight: float, title_height: float = 0.1):
    fig, axs = pitch.grid(nrows=1, ncols=ncols, figheight=figheight, title_height=title_height,
                          endnote_height=0.05, grid_height=0.93 - title_height - 0.05, space=0.04, axis=False)
    fig.set_facecolor(SURFACE)
    pitches = list(np.atleast_1d(axs["pitch"]))
    return fig, pitches, axs["title"], axs["endnote"]


def _header(ax, title: str, subtitle: str, kpis: Optional[Sequence[str]] = None):
    ax.text(0, 1, title, ha="left", va="top", fontsize=17, fontweight="bold", color=INK, transform=ax.transAxes)
    ax.text(0, 0.66 if kpis else 0.62, subtitle, ha="left", va="top", fontsize=10.5, color=INK_2, linespacing=1.4,
            transform=ax.transAxes)
    if kpis:
        ax.text(0, 0.3, "   ·   ".join(kpis), ha="left", va="center", fontsize=10.5, color=INK, transform=ax.transAxes)


def _footer(fig, ax, colorbar: Optional[Tuple[TwoSlopeNorm, str, list]] = None, cmap=DIVERGING):
    ax.text(0, 0.5, SOURCE, ha="left", va="center", fontsize=8.5, color=MUTED, transform=ax.transAxes)
    if colorbar:
        norm, label, ticks = colorbar
        box = ax.get_position()
        cax = fig.add_axes([box.x0 + box.width * 0.5, box.y0 + box.height * 0.35, box.width * 0.46, box.height * 0.22])
        cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation="horizontal")
        cb.outline.set_visible(False)
        cb.set_ticks(ticks)
        cb.ax.tick_params(labelsize=8.5, colors=INK_2, length=0)
        cax.set_title(label, fontsize=9, color=INK_2, pad=3)


def formation_strength(formation: str, panels: List[Tuple[str, List[Dict]]], title: str, subtitle: str, path: str):
    """panels: [(heading, slots)], slots in formation order: {score 0..100 or None, players [(name, minutes)]}.
    Each slot is drawn where the formation puts it and coloured by its score against the panel's benchmark."""
    pitch = _pitch()
    fig, axs, tax, eax = _canvas(pitch, len(panels), figheight=11.5 if len(panels) > 1 else 12)
    norm = TwoSlopeNorm(vmin=0, vcenter=50, vmax=100)
    layout = pitch.get_formation(formation)
    for ax, (heading, slots) in zip(axs, panels):
        for pos, slot in zip(layout, slots):
            x, y = pos.x, pos.y
            score = slot.get("score")
            color = DIVERGING(norm(score)) if score is not None else NEUTRAL
            pitch.scatter(x, y, s=2000, color=color, edgecolors=SURFACE, linewidth=2.5, ax=ax, zorder=3)
            txt = "#ffffff" if score is not None and abs(score - 50) > 22 else INK
            pitch.annotate("—" if score is None else f"{score:.0f}", (x, y), ax=ax, ha="center", va="center",
                           fontsize=14, fontweight="bold", color=txt, zorder=4)
            names = slot.get("players") or []
            label = "\n".join(f"{n.split()[-1] if len(n) > 14 else n} · {m:.0f}′" for n, m in names[:2])
            pitch.annotate(label, (x - 6.8, y), ax=ax, ha="center", va="top", fontsize=8.4, color=INK, zorder=4,
                           linespacing=1.25)
        ax.set_title(heading, fontsize=12.5, color=INK, pad=6, fontweight="bold")
    _header(tax, title, subtitle)
    _footer(fig, eax, (norm, "слабее  ←  медиана эталона = 50  →  сильнее", [0, 25, 50, 75, 100]))
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def pass_networks(panels, title: str, subtitle: str, path: str):
    """panels: [(heading, nodes, edges, style_line)]; nodes - x, y, per_match, code, label; edges - a, b, per_match.
    Side by side, same scales, so two periods (or two teams) compare at a glance."""
    pitch = _pitch()
    fig, axs, tax, eax = _canvas(pitch, len(panels), figheight=11.5)
    emax = max((e["per_match"].max() for _, _, e, _ in panels if len(e)), default=1)
    nmax = max(n["per_match"].max() for _, n, _, _ in panels)
    for ax, (heading, nodes, edges, line) in zip(axs, panels):
        for e in edges.itertuples():
            a, b = nodes.loc[e.a], nodes.loc[e.b]
            pitch.lines(a.x, a.y, b.x, b.y, lw=1 + 7 * e.per_match / emax, color=BLUE,
                        alpha=0.25 + 0.6 * e.per_match / emax, ax=ax, zorder=1)
        pitch.scatter(nodes["x"], nodes["y"], s=420 + 900 * nodes["per_match"] / nmax, color=SURFACE,
                      edgecolors=BLUE, linewidth=2.2, ax=ax, zorder=2)
        for p in nodes.itertuples():
            pitch.annotate(p.code, (p.x, p.y), ax=ax, ha="center", va="center", fontsize=8.2, fontweight="bold",
                           color=BLUE, zorder=3)
            surname = p.label.split()[-1] if p.label else ""
            pitch.annotate(surname, (p.x - 4.4, p.y), ax=ax, ha="center", va="top", fontsize=9, color=INK, zorder=3)
        ax.set_title(heading, fontsize=13, color=INK, pad=8, fontweight="bold")
        ax.text(0.5, -0.015, line, transform=ax.transAxes, ha="center", va="top", fontsize=9.5, color=INK_2)
    _header(tax, title, subtitle)
    _footer(fig, eax)
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)


# zones of the attacking half shaped by the penalty area: outside the box, the box channels, six-yard box
X_EDGES = [60, 84, 102, 114, 120]
Y_EDGES = [0, 18, 30, 50, 62, 80]


def zone_sum(x, y, w) -> np.ndarray:
    h, _, _ = np.histogram2d(x, y, bins=[X_EDGES, Y_EDGES], weights=w)
    return h


def conceded(shots_against, team_matches: int, league_zone_per_match: np.ndarray, title: str, subtitle: str,
             path: str, kpis: Optional[List[str]] = None):
    """Left: every shot the team conceded (size = xG, red = goal). Right: xG conceded per match by zone
    minus the league average per team and match (red = worse than the league)."""
    pitch = _pitch(half=True)
    fig, axs, tax, eax = _canvas(pitch, 2, figheight=8.6, title_height=0.17)
    s = shots_against
    goal = s["outcome"] == "Goal"
    sizes = 40 + 900 * s["shot_xg"].fillna(0)
    pitch.scatter(s.loc[~goal, "x"], s.loc[~goal, "y"], s=sizes[~goal], facecolors="none", edgecolors=MUTED,
                  linewidth=1.1, alpha=0.8, ax=axs[0], zorder=2)
    pitch.scatter(s.loc[goal, "x"], s.loc[goal, "y"], s=sizes[goal], color=RED, edgecolors=SURFACE,
                  linewidth=1.4, ax=axs[0], zorder=3)
    axs[0].set_title("Удары соперников: размер = xG, красные — голы", fontsize=11, color=INK_2, pad=6)

    team_zone = zone_sum(s["x"], s["y"], s["shot_xg"].fillna(0)) / team_matches
    diff = team_zone - league_zone_per_match
    lim = max(0.05, float(np.abs(diff).max()))
    norm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
    rev = DIVERGING.reversed()            # here more conceded is worse -> red
    for i in range(len(X_EDGES) - 1):
        for j in range(len(Y_EDGES) - 1):
            x0, x1, y0, y1 = X_EDGES[i], X_EDGES[i + 1], Y_EDGES[j], Y_EDGES[j + 1]
            d = diff[i, j]
            # vertical pitch: pitch y -> plot x, pitch x -> plot y
            axs[1].add_patch(Rectangle((y0, x0), y1 - y0, x1 - x0, facecolor=rev(norm(d)), edgecolor=SURFACE,
                                       linewidth=2, zorder=1, alpha=0.95))
            if team_zone[i, j] >= 0.02 or abs(d) >= 0.01:
                c = "#ffffff" if abs(d) > lim * 0.55 else INK
                axs[1].text((y0 + y1) / 2, (x0 + x1) / 2, f"{d:+.2f}", ha="center", va="center", fontsize=9.5,
                            color=c, zorder=4, fontweight="bold" if abs(d) > lim * 0.4 else "normal")
    axs[1].set_title("xG пропущенных за матч по зонам минус среднее по лиге", fontsize=11, color=INK_2, pad=6)
    _header(tax, title, subtitle, kpis)
    _footer(fig, eax, (norm, "меньше лиги  ←  →  больше лиги (хуже)", [-lim, 0, lim]), cmap=rev)
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
