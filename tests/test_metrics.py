"""Per-90 metrics and percentiles on a tiny hand-made match where the answers are known."""
import pandas as pd
import pytest

from fi import metrics as fm


def ev_row(**kw):
    base = {"match_id": 1, "id": kw.pop("id", None), "type": "Pass", "team": "A", "player": "a1", "player_id": 1,
            "position": "Center Back", "x": 30.0, "y": 40.0, "end_x": None, "end_y": None, "outcome": None,
            "sub_type": None, "pass_recipient": None, "pass_shot_assist": False, "shot_xg": None,
            "shot_key_pass_id": None, "aerial_won": False, "minute": 10}
    base.update(kw)
    return base


@pytest.fixture
def match():
    rows = []
    # team A: 6 passes (60 % of the match's passes), team B: 4
    for i in range(6):
        rows.append(ev_row(id=f"a{i}", end_x=45.0, end_y=40.0))                       # progressive? 15 yards but ends at 45 < 60 -> no
    rows.append(ev_row(id="prog", end_x=75.0, end_y=40.0, x=62.0))                      # progressive: 13 yards, ends in opp half
    rows[-1]["type"] = "Pass"
    for i in range(4):
        rows.append(ev_row(id=f"b{i}", team="B", player="b1", player_id=2, position="Center Forward", end_x=60.0, end_y=40.0))
    # a1 wins two tackles; b1 shoots twice (0.3 + 0.1 xG), one goal, assisted by a pass from b1 itself for simplicity
    rows += [ev_row(type="Duel", sub_type="Tackle", outcome="Won"), ev_row(type="Duel", sub_type="Tackle", outcome="Lost In Play")]
    rows += [ev_row(id="s1", type="Shot", team="B", player="b1", player_id=2, position="Center Forward", shot_xg=0.3,
                    outcome="Goal", shot_key_pass_id="b0", x=110.0, y=40.0),
             ev_row(id="s2", type="Shot", team="B", player="b1", player_id=2, position="Center Forward", shot_xg=0.1,
                    outcome="Off T", x=100.0, y=30.0)]
    ev = pd.DataFrame(rows)
    spells = pd.DataFrame([
        {"match_id": 1, "team": "A", "player_id": 1, "player": "a1", "nickname": None, "position": "Center Back", "start": 0, "end": 90, "minutes": 90},
        {"match_id": 1, "team": "B", "player_id": 2, "player": "b1", "nickname": None, "position": "Center Forward", "start": 0, "end": 90, "minutes": 90},
    ])
    return ev, spells


def test_possession_share(match):
    ev, _ = match
    p = fm.possession_share(ev).set_index("team")["share"]
    assert p["A"] == pytest.approx(7 / 11) and p["B"] == pytest.approx(4 / 11)


def test_player_metrics(match):
    ev, spells = match
    t = fm.player_table(ev, spells).set_index("player")
    a, b = t.loc["a1"], t.loc["b1"]
    assert a["group"] == "CB" and b["group"] == "CF"
    assert a["prog_passes"] == pytest.approx(1.0)              # one progressive pass in 90 minutes
    # one tackle won, scaled by 0.5 / opponent possession (4/11): opponent had the ball less -> fewer chances to defend
    assert a["tackle_int_padj"] == pytest.approx(0.5 / (4 / 11))
    assert b["npxg"] == pytest.approx(0.4)
    assert b["finishing"] == pytest.approx(1 - 0.4)
    assert b["xa"] == pytest.approx(0.3)                       # the pass b0 led to the 0.3 xG shot


def test_percentiles_direction():
    t = pd.DataFrame({"player_id": [1, 2, 3], "team": ["A", "B", "C"], "group": ["CM"] * 3, "minutes": [1000] * 3,
                      **{m: [1.0, 2.0, 3.0] for m in fm.ROLE_METRICS["CM"]}})
    p = fm.percentiles(t).set_index("player_id")
    assert p.loc[3, "pct_prog_passes"] > p.loc[1, "pct_prog_passes"]       # more is better
    assert p.loc[3, "pct_losses"] < p.loc[1, "pct_losses"]                 # more losses is worse
