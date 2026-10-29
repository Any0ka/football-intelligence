"""Team shape: where each slot of the formation stands in a match, and how the others move with it.

Every team-match is split at tactical shifts; in each part the average location of a slot's on-ball actions
gives one "shape" of 11 points. From match to match the shape flexes: when a right back plays higher, the
right winger and the right midfielder tend to stand differently too. A Gaussian model of the 22 coordinates
(spread pooled over all teams playing the formation, centred on each team's own average) answers "if this
slot stands here, where do the others stand on average":

    E[others | slot k] = mean_others + S_ok S_kk^-1 (slot_k - mean_k)

It is an association learnt from real matches, not a simulation of tactics: moving one player on the
board shows how teams usually were arranged when that player stood there.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from mplsoccer import Pitch
from sklearn.covariance import LedoitWolf

POSITION_NAMES = {
    1: "Goalkeeper", 2: "Right Back", 3: "Right Center Back", 4: "Center Back", 5: "Left Center Back", 6: "Left Back",
    7: "Right Wing Back", 8: "Left Wing Back", 9: "Right Defensive Midfield", 10: "Center Defensive Midfield",
    11: "Left Defensive Midfield", 12: "Right Midfield", 13: "Right Center Midfield", 14: "Center Midfield",
    15: "Left Center Midfield", 16: "Left Midfield", 17: "Right Wing", 18: "Right Attacking Midfield",
    19: "Center Attacking Midfield", 20: "Left Attacking Midfield", 21: "Left Wing", 22: "Right Center Forward",
    23: "Center Forward", 24: "Left Center Forward", 25: "Secondary Striker",
}
MIN_EVENTS = 8             # actions of a slot in one part of a match before its average location means something
TACTICS = {"Starting XI", "Tactical Shift"}


@lru_cache(maxsize=None)
def _pitch() -> Pitch:
    return Pitch(pitch_type="statsbomb")


@lru_cache(maxsize=None)
def _template() -> pd.DataFrame:
    """Typical location of every StatsBomb position id over all formations mplsoccer knows."""
    df = _pitch().formations_dataframe.explode("statsbomb")
    return df.groupby("statsbomb")[["x", "y"]].mean()


def layout(formation: str):
    return _pitch().get_formation(str(formation))


@lru_cache(maxsize=None)
def slot_of(formation: str) -> Dict[int, int]:
    """StatsBomb position id -> slot index in the formation. Positions the formation does not list (a
    'centre midfield' in a 4-2-3-1 week) go to the nearest slot."""
    pos = layout(formation)
    out: Dict[int, int] = {}
    for i, p in enumerate(pos):
        for pid in p.statsbomb:
            out.setdefault(int(pid), i)
    xy = np.array([[p.x, p.y] for p in pos])
    for pid, (x, y) in _template().iterrows():
        if int(pid) not in out:
            out[int(pid)] = int(np.argmin(((xy - [x, y]) ** 2).sum(axis=1)))
    return out


def _parts(ev: pd.DataFrame) -> pd.DataFrame:
    """Events with the formation in force and the part of the match (a new part at every tactical shift)."""
    e = ev.sort_values(["match_id", "index"])
    tac = e["type"].isin(TACTICS)
    e = e.assign(part=tac.astype(int).groupby([e["match_id"], e["team"]]).cumsum(),
                 form=e["formation"].where(tac))
    e["form"] = e.groupby(["match_id", "team"])["form"].ffill()
    return e


def match_shapes(ev: pd.DataFrame, spells: pd.DataFrame) -> pd.DataFrame:
    """One row per team, match part and slot: mean x, y of the slot's actions (only complete parts)."""
    pos_id = spells.drop_duplicates("position").set_index("position")["position_id"]
    e = _parts(ev)
    e = e[e["x"].notna() & e["position"].notna() & e["form"].notna() & ~e["type"].isin(TACTICS)]
    e = e.assign(pid=e["position"].map(pos_id))
    rows = []
    for form, g in e.groupby("form"):
        g = g.assign(slot=g["pid"].map(slot_of(form)))
        a = g.groupby(["team", "match_id", "part", "slot"]).agg(x=("x", "mean"), y=("y", "mean"), n=("x", "size"))
        rows.append(a.reset_index().assign(formation=form))
    s = pd.concat(rows, ignore_index=True)
    s = s[s["n"] >= MIN_EVENTS]
    size = {f: len(layout(f)) for f in s["formation"].unique()}
    full = s.groupby(["team", "match_id", "part", "formation"])["slot"].transform("nunique")
    return s[full == s["formation"].map(size)]


def main_formation(shapes: pd.DataFrame, team: str) -> Tuple[str, float]:
    """The formation a team spent most of its actions in, and that share."""
    t = shapes[shapes["team"] == team].groupby("formation")["n"].sum()
    return str(t.idxmax()), float(t.max() / t.sum())


def model(shapes: pd.DataFrame, formation: str, min_parts: int = 3) -> Dict:
    """Team mean shapes and, per slot, the 22x2 response matrix of all coordinates to that slot's move."""
    s = shapes[shapes["formation"] == formation]
    wide = s.pivot_table(index=["team", "match_id", "part"], columns="slot", values=["x", "y"])
    k = len(layout(formation))
    cols = [(c, i) for i in range(k) for c in ("x", "y")]           # x0, y0, x1, y1, ...
    wide = wide.reindex(columns=pd.MultiIndex.from_tuples(cols)).dropna()
    counts = wide.groupby(level="team").size()
    wide = wide[wide.index.get_level_values("team").isin(counts[counts >= min_parts].index)]
    if len(wide) < 4 * k:
        raise ValueError(f"{formation}: {len(wide)} complete match parts are too few for a {2 * k}-dim covariance")
    means = wide.groupby(level="team").mean()
    resid = wide.to_numpy() - means.loc[wide.index.get_level_values("team")].to_numpy()
    cov = LedoitWolf().fit(resid).covariance_
    B = []
    for i in range(k):
        idx = [2 * i, 2 * i + 1]
        B.append(cov[:, idx] @ np.linalg.inv(cov[np.ix_(idx, idx)]))
    return {"formation": formation, "parts": int(len(wide)), "teams": int(len(means)),
            "means": {t: means.loc[t].to_numpy().reshape(k, 2) for t in means.index},
            "B": np.array(B), "cov": cov, "sd": np.sqrt(np.diag(cov)).reshape(k, 2)}


def respond(m: Dict, team: str, slot: int, xy: Tuple[float, float]) -> np.ndarray:
    """Expected shape (k x 2) of the team when `slot` stands at xy."""
    mean = m["means"][team]
    delta = np.asarray(xy, float) - mean[slot]
    return mean + (m["B"][slot] @ delta).reshape(-1, 2)


def couplings(m: Dict, slot: int, top: int = 3) -> List[Tuple[int, float]]:
    """Slots that move most when `slot` moves one yard (largest singular value of their 2x2 response)."""
    B = m["B"][slot].reshape(-1, 2, 2)
    gain = [(j, float(np.linalg.svd(b, compute_uv=False)[0])) for j, b in enumerate(B) if j != slot]
    return sorted(gain, key=lambda t: -t[1])[:top]
