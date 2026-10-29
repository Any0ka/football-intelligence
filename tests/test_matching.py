"""Name matching between StatsBomb (legal names) and Transfermarkt (common names)."""
import pytest

from fi.matching import club_key, country_key, name_score, norm


def test_norm_strips_accents_and_punctuation():
    assert norm("N'Golo Kanté") == "ngolo kante"
    assert norm("Branislav Ivanović") == "branislav ivanovic"
    assert norm("Martin Ødegaard") == "martin odegaard"
    assert norm("Gylfi Þór Sigurðsson") == "gylfi thor sigurdsson"
    assert norm("Hakan Çalhanoğlu") == "hakan calhanoglu"


def test_club_key_ignores_fc_afc():
    assert club_key("Chelsea FC") == club_key("Chelsea") == "chelsea"
    assert club_key("AFC Bournemouth") == club_key("AFC Bournemouth") == "bournemouth"
    assert country_key("Côte d'Ivoire") == country_key("Ivory Coast")


@pytest.mark.parametrize("sb, tm", [
    (["Cesc Fàbregas", "Francesc Fàbregas i Soler"], "Cesc Fàbregas"),
    (["Willian", "Willian Borges da Silva"], "Willian"),
    (["John Obi Mikel", "John Michael Nchekwube Obinna"], "Mikel John Obi"),
    (["Baba Rahman", "Abdul Rahman Baba"], "Abdul Rahman Baba"),
    (["Timothy Michael Krul"], "Tim Krul"),
    (["Falcao", "Radamel Falcao García Zárate"], "Radamel Falcao"),
])
def test_same_player_scores_high(sb, tm):
    assert name_score(sb, tm) >= 0.85


@pytest.mark.parametrize("sb, tm", [
    (["Jordan Lyden"], "Jordan Ayew"),          # shared first name only - was a false match
    (["Gary Cahill"], "Gary Neville"),
    (["Eden Hazard"], "Thorgan Hazard"),
])
def test_different_players_score_low(sb, tm):
    assert name_score(sb, tm) < 0.72
