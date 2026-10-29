"""Team-level tactical structure: pass network by formation slot and a few style numbers."""
from __future__ import annotations

from typing import Iterable

import pandas as pd

SHORT = {
    "Goalkeeper": "GK", "Right Back": "RB", "Right Center Back": "RCB", "Center Back": "CB", "Left Center Back": "LCB",
    "Left Back": "LB", "Right Wing Back": "RWB", "Left Wing Back": "LWB",
    "Right Defensive Midfield": "RDM", "Center Defensive Midfield": "CDM", "Left Defensive Midfield": "LDM",
    "Right Center Midfield": "RCM", "Center Midfield": "CM", "Left Center Midfield": "LCM",
    "Right Midfield": "RM", "Left Midfield": "LM", "Right Wing": "RW", "Left Wing": "LW",
    "Right Attacking Midfield": "RAM", "Center Attacking Midfield": "CAM", "Left Attacking Midfield": "LAM",
    "Right Center Forward": "RCF", "Center Forward": "CF", "Left Center Forward": "LCF", "Secondary Striker": "SS",
}


# In a 4-2-3-1 StatsBomb labels the same two deep midfielders "centre" in some matches and "defensive"
# in others, and the wide attackers "wing" or "midfield"; one slot per role keeps the picture honest.
CANONICAL_4231 = {
    "Left Center Midfield": "Left Defensive Midfield", "Right Center Midfield": "Right Defensive Midfield",
    "Center Defensive Midfield": "Right Defensive Midfield", "Center Midfield": "Right Defensive Midfield",
    "Left Midfield": "Left Wing", "Right Midfield": "Right Wing",
    "Left Attacking Midfield": "Left Wing", "Right Attacking Midfield": "Right Wing",
    "Center Back": "Right Center Back", "Secondary Striker": "Center Attacking Midfield",
}


def _recipient_positions(passes: pd.DataFrame, spells: pd.DataFrame) -> pd.Series:
    """Position of the pass recipient at the minute of the pass, from the lineup spells."""
    sp = spells[["match_id", "player", "position", "start", "end"]].rename(columns={"player": "pass_recipient",
                                                                                   "position": "recipient_position"})
    m = passes[["match_id", "pass_recipient", "minute"]].reset_index().merge(sp, on=["match_id", "pass_recipient"])
    m = m[(m["minute"] >= m["start"]) & (m["minute"] < m["end"])].drop_duplicates("index")
    return m.set_index("index")["recipient_position"]


def pass_network(ev: pd.DataFrame, spells: pd.DataFrame, team: str, match_ids: Iterable[int],
                 min_pair_passes_per_match: float = 2.0, min_share: float = 0.25, canonical=CANONICAL_4231):
    """Nodes are formation slots (LB, LCM, CAM...), not players: a player who plays left back one week and
    right back the next does not end up averaged into midfield. A node sits at the mean location of the
    passes made and received in that slot, before the team's first substitution."""
    match_ids = list(match_ids)
    n = len(match_ids)
    sub = ev[(ev["team"] == team) & ev["match_id"].isin(match_ids)]
    first_sub = (sub[sub["type"] == "Substitution"].groupby("match_id")["minute"].min()
                 .reindex(match_ids).fillna(95))
    sub = sub[sub["minute"] < sub["match_id"].map(first_sub)]
    passes = sub[(sub["type"] == "Pass") & sub["outcome"].isna() & sub["pass_recipient"].notna()].copy()
    sp = spells[(spells["team"] == team) & spells["match_id"].isin(match_ids)].copy()
    canon = lambda s: s.replace(canonical or {})
    sp["position"] = canon(sp["position"])
    passes["position"] = canon(passes["position"])
    passes["recipient_position"] = _recipient_positions(passes, sp)
    passes = passes.dropna(subset=["position", "recipient_position"])

    made = passes[["match_id", "position", "x", "y"]]
    got = passes[["match_id", "recipient_position", "end_x", "end_y"]].rename(
        columns={"recipient_position": "position", "end_x": "x", "end_y": "y"})
    allp = pd.concat([made, got])
    nodes = allp.groupby("position").agg(x=("x", "mean"), y=("y", "mean"), touches=("x", "size"),
                                         matches=("match_id", "nunique"))
    nodes = nodes[nodes["matches"] >= max(2, min_share * n)].copy()
    nodes["per_match"] = nodes["touches"] / nodes["matches"]
    nick = sp.groupby("player")["nickname"].first()
    mins = sp.groupby(["position", "player"])["minutes"].sum()
    main = {}
    for pos in nodes.index:
        if pos in mins.index.get_level_values(0):
            p = mins.loc[pos].idxmax()
            main[pos] = nick.get(p) if isinstance(nick.get(p), str) else p
    nodes["code"] = [SHORT.get(p, p) for p in nodes.index]
    nodes["label"] = [main.get(p, "") for p in nodes.index]

    pairs = passes[passes["position"].isin(nodes.index) & passes["recipient_position"].isin(nodes.index)
                   & (passes["position"] != passes["recipient_position"])]
    key = [tuple(sorted(t)) for t in zip(pairs["position"], pairs["recipient_position"])]
    edges = pd.Series(key).value_counts().rename("passes").reset_index()
    edges.columns = ["pair", "passes"]
    edges["a"] = edges["pair"].str[0]
    edges["b"] = edges["pair"].str[1]
    edges["per_match"] = edges["passes"] / n
    edges = edges[edges["per_match"] >= min_pair_passes_per_match].drop(columns="pair")
    return nodes, edges


def league_table(matches: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Points, goals and xG for and against per team, sorted like the league table."""
    rows = []
    for m in matches.itertuples():
        for side, opp, gf, ga in ((m.home, m.away, m.home_score, m.away_score), (m.away, m.home, m.away_score, m.home_score)):
            rows.append({"team": side, "opp": opp, "match_id": m.match_id, "gf": gf, "ga": ga,
                         "pts": 3 if gf > ga else 1 if gf == ga else 0})
    t = pd.DataFrame(rows)
    shots = ev[ev["type"] == "Shot"]
    xg = shots.groupby(["match_id", "team"])["shot_xg"].sum().rename("xg").reset_index()
    t = t.merge(xg, on=["match_id", "team"], how="left").merge(
        xg.rename(columns={"team": "opp", "xg": "xga"}), on=["match_id", "opp"], how="left").fillna({"xg": 0, "xga": 0})
    agg = t.groupby("team").agg(matches=("pts", "size"), pts=("pts", "sum"), gf=("gf", "sum"), ga=("ga", "sum"),
                                xg=("xg", "sum"), xga=("xga", "sum"))
    agg["xgd"] = agg["xg"] - agg["xga"]
    agg = agg.sort_values(["pts", "gf"], ascending=False)
    agg["place"] = range(1, len(agg) + 1)
    agg["xgd_rank"] = agg["xgd"].rank(ascending=False, method="min").astype(int)
    agg["xga_rank"] = agg["xga"].rank(method="min").astype(int)
    return agg


def style(ev: pd.DataFrame, team: str, match_ids: Iterable[int]) -> dict:
    """A few style numbers: possession, how high the team presses (PPDA), how direct it plays."""
    match_ids = list(match_ids)
    m = ev[ev["match_id"].isin(match_ids)]
    own, opp = m[m["team"] == team], m[m["team"] != team]
    own_passes, opp_passes = own[own["type"] == "Pass"], opp[opp["type"] == "Pass"]
    # PPDA: opponent passes in their own 60% of the pitch per our defensive action there (lower = more pressing)
    opp_build = opp_passes[opp_passes["x"] <= 72]
    def_actions = own[own["type"].isin(["Duel", "Interception", "Foul Committed", "Block"]) & (own["x"] >= 48)]
    long_share = (own_passes["pass_length"] >= 32).mean()       # 32 yards+ (StatsBomb units are yards)
    return {"possession": len(own_passes) / max(1, len(own_passes) + len(opp_passes)),
            "ppda": len(opp_build) / max(1, len(def_actions)),
            "long_pass_share": float(long_share),
            "passes_per_match": len(own_passes) / max(1, len(match_ids))}
