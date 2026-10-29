"""AI assistant's tools: they must give the same numbers as the page (no calls to the model here)."""
import pytest

from app import assistant as ai

pytestmark = pytest.mark.skipif(not (ai.DATA / "index.json").exists(), reason="app data not built (python -m app.build)")


@pytest.fixture(scope="module")
def tools():
    events = []
    t = ai.Tools(ai.DATA_.load(), ai.Session("test"), events.append)
    t.events = events
    return t


def test_replacements_match_the_page(tools):
    # the page shows Morata 0.56, Bastón 0.42, Dybala 0.37 for Barcelona's striker
    out = tools.run("find_replacements", {"team": "Barcelona", "slot": "ST"})
    assert [c["name"] for c in out["candidates"]] == ["Álvaro Morata", "Borja Bastón", "Paulo Dybala"]
    assert [round(c["topsis"], 2) for c in out["candidates"]] == [0.56, 0.42, 0.37]


def test_transfer_plan_matches_the_page(tools):
    out = tools.run("transfer_plan", {"team": "Chelsea", "budget_m": 120})
    assert out["spent"] == "€103 млн"
    assert {p["name"] for p in out["plan"]} == {"Yoan Cardinale", "Alessandro Florenzi", "Virgil van Dijk",
                                                "Marcelo", "Paulo Dybala"}
    assert "value_2018" not in out["plan"][0]                  # the future only on request


def test_names_are_found_without_accents_and_cyrillic_is_refused(tools):
    assert tools.run("get_player", {"name": "Ivanovic"})["players"][0]["name"] == "Branislav Ivanović"
    assert "error" in tools.run("get_player", {"name": "Иванович"})
    with pytest.raises(LookupError):
        tools.run("get_club", {"team": "Челси"})
    assert tools.run("get_club", {"team": "atletico madrid"})["team"] == "Atlético Madrid"


def test_show_in_app_sends_a_validated_event(tools):
    tools.run("show_in_app", {"team": "Juventus", "slot": "rwb", "tab": "replace"})
    assert tools.events[-1] == {"type": "show", "team": "Juventus", "league": "Serie A", "slot": "RWB", "tab": "replace"}
    with pytest.raises(LookupError):
        tools.run("show_in_app", {"team": "Juventus", "slot": "XX"})


def test_tool_inputs_are_checked():
    assert ai._validate("find_replacements", {"team": "Chelsea", "slot": "ST"}) is None
    assert ai._validate("find_replacements", {"team": "Chelsea"})                       # slot missing
    assert ai._validate("find_replacements", {"team": "Chelsea", "slot": "ST", "top": "5"})
    assert ai._validate("search_players", {"sort_by": "best"})                           # not in the enum
    assert ai._validate("find_replacements", {"team": "Chelsea", "slot": "ST", "weights": {"luck": 1}})
