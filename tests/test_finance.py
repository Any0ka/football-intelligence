"""Squad return by market value: who stayed, joined and left, and the return of those who stayed."""
import numpy as np
import pandas as pd

from fi import finance as ff


def squad(season, club, players):
    return pd.DataFrame({"season": season, "club_id": club, "player_id": players})


def data(n_extra=0):
    # club 1: a and b at the end of 2014; a stays, b leaves, c joins in 2015. extra players keep the squad big enough
    extra = list(range(100, 100 + n_extra))
    sq = pd.concat([squad(2014, 1, ["a", "b", *extra]), squad(2015, 1, ["a", "c", *extra]), squad(2015, 2, ["b"])])
    vals = pd.DataFrame({"season": [2014, 2014, 2015, 2015, 2015], "player_id": ["a", "b", "a", "c", "b"],
                         "value": [10e6, 20e6, 15e6, 5e6, 25e6]})
    return sq, vals


def test_squad_is_the_club_of_the_last_appearance_of_the_season():
    ap = pd.DataFrame({"season": [2015, 2015, 2015], "player_id": ["a", "a", "b"], "club_id": [1, 2, 1],
                       "date": pd.to_datetime(["2015-09-01", "2016-02-01", "2016-01-01"])})
    sq = ff.squads(ap).set_index("player_id")["club_id"]
    assert sq["a"] == 2 and sq["b"] == 1


def test_moves_and_return_of_the_players_who_stayed():
    sq, vals = data(n_extra=ff.MIN_SQUAD)
    mv = ff.moves(sq, vals).set_index(["club_id", "player_id"])
    assert mv.loc[(1, "a"), "status"] == "stayed" and mv.loc[(1, "c"), "status"] == "joined"
    assert mv.loc[(1, "b"), "status"] == "left" and mv.loc[(1, "b"), "value_prev"] == 20e6
    r = ff.returns(ff.moves(sq, vals)).set_index("club_id").loc[1]
    assert r["season"] == 2015 and r["stayed"] == 1
    assert np.isclose(r["ret"], 15 / 10 - 1)                   # a: 10 -> 15; b's sale and c's arrival do not count
    assert r["joined_value"] == 5e6 and r["left_value"] == 20e6
    assert r["squad_value"] == 20e6                           # a + c at the end of 2015 (extras have no value)


def test_no_return_for_a_squad_outside_the_covered_leagues():
    sq, vals = data(n_extra=0)                                 # two players: the club was not in a covered league
    r = ff.returns(ff.moves(sq, vals)).set_index("club_id").loc[1]
    assert np.isnan(r["ret"]) and np.isnan(r["squad"])
    assert np.isnan(r["joined"]) and np.isnan(r["left"])      # no arrivals / departures against a missing squad
