"""Team shape: position ids map onto formation slots; the Gaussian response moves correlated slots together."""
import numpy as np
import pandas as pd

from fi import shape as fs


def test_every_position_maps_to_a_slot():
    for formation in ("4231", "442", "433", "352"):
        m = fs.slot_of(formation)
        assert set(range(1, 26)) <= set(m)
        assert m[1] == 0                                   # goalkeeper
        assert set(m.values()) == set(range(len(fs.layout(formation))))


def test_4231_holding_midfielder_goes_to_a_holding_slot():
    names = [p.name for p in fs.layout("4231")]
    assert names[fs.slot_of("4231")[10]] in ("RDM", "LDM")    # Center Defensive Midfield
    assert names[fs.slot_of("4231")[23]] == "ST"


def synthetic_shapes(n=60, seed=0):
    """Two teams in a 4-2-3-1; the right back and right winger move up and down together."""
    rng = np.random.default_rng(seed)
    pos = fs.layout("4231")
    rows = []
    for team in ("A", "B"):
        for k in range(n):
            push = rng.normal(0, 4)
            for i, p in enumerate(pos):
                dx = push if p.name in ("RB", "RW") else rng.normal(0, 1)
                rows.append({"team": team, "match_id": k, "part": 1, "slot": i, "formation": "4231",
                             "x": p.x + dx, "y": p.y + rng.normal(0, 1), "n": 20})
    return pd.DataFrame(rows)


def test_response_moves_the_correlated_slot():
    m = fs.model(synthetic_shapes(), "4231")
    names = [p.name for p in fs.layout("4231")]
    rb, rw, gk = names.index("RB"), names.index("RW"), names.index("GK")
    mean = m["means"]["A"]
    moved = fs.respond(m, "A", rb, mean[rb] + [10, 0])
    assert moved[rw][0] - mean[rw][0] > 6                  # winger follows the full back up
    assert abs(moved[gk][0] - mean[gk][0]) < 2              # goalkeeper barely moves
    assert fs.couplings(m, rb, top=1)[0][0] == rw
