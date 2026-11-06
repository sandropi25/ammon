"""Stemmi, colori e numeri di maglia letti da ESPN (nessuna richiesta in più)."""
import httpx
import pytest
import respx

from ammonizioni.fonti.espn import URL_ESPN, Espn, _maglia, stile_squadra
from ammonizioni.fonti.tipi import StileSquadra

LOGO = "https://a.espncdn.com/i/teamlogos/soccer/500/2572.png"


@pytest.fixture
def espn():
    with httpx.Client() as client:
        yield Espn(client=client, dormi=lambda s: None)


def test_stile_dallo_scoreboard():
    team = {"id": "2572", "logo": LOGO, "color": "4169e1", "alternateColor": "FFFFFF"}
    assert stile_squadra(team) == StileSquadra(LOGO, "#4169E1", "#FFFFFF")


def test_stile_dal_summary_usa_il_logo_default():
    team = {
        "id": "2572", "color": "000000",
        "logos": [
            {"href": "https://a.espncdn.com/i/teamlogos/soccer/500-dark/2572.png", "rel": ["full", "dark"]},
            {"href": LOGO, "rel": ["full", "default"]},
        ],
    }
    assert stile_squadra(team) == StileSquadra(LOGO, "#000000", None)


@pytest.mark.parametrize("team", [
    {"id": "1"},
    {"id": "1", "logo": "http://insicuro.example/x.png", "color": "rosso"},
    {"id": "1", "logo": "javascript:alert(1)", "color": "12345", "alternateColor": "GGGGGG"},
    None,
])
def test_stile_assente_o_non_valido(team):
    assert stile_squadra(team) is None


@pytest.mark.parametrize("valore,atteso", [
    ("10", 10), ("1", 1), (" 7 ", 7), (23, 23), ("0", 0),
    ("100", None), ("-1", None), ("abc", None), (None, None), ("", None), (True, None),
])
def test_numero_di_maglia(valore, atteso):
    assert _maglia(valore) == atteso


@respx.mock
def test_calendario_porta_stemmi_e_colori(espn):
    evento = {
        "id": "9", "date": "2026-11-08T14:00Z",
        "status": {"type": {"name": "STATUS_SCHEDULED"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "0",
             "team": {"id": "2572", "displayName": "Como", "logo": LOGO, "color": "4169E1",
                      "alternateColor": "FFFFFF"}},
            {"homeAway": "away", "score": "0",
             "team": {"id": "17530", "displayName": "Venezia"}},
        ]}],
    }
    respx.get(f"{URL_ESPN}/ita.1/scoreboard", params={"dates": "2026", "limit": "1000"}).mock(
        return_value=httpx.Response(200, json={"events": [evento]})
    )
    respx.get(f"{URL_ESPN}/ita.1/scoreboard", params={"dates": "2027", "limit": "1000"}).mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    (p,) = espn.partite(135, 2026)
    assert p.casa_stile == StileSquadra(LOGO, "#4169E1", "#FFFFFF")
    assert p.trasferta_stile is None


def _summary():
    posizioni = ["G", "RB", "CD-R", "CD-L", "LB", "RM", "CM", "LM", "AM", "RF", "LF"]
    roster = [
        {
            "starter": True, "subbedIn": False, "subbedOut": False, "jersey": str(i),
            "position": {"abbreviation": a}, "formationPlace": str(i),
            "athlete": {"id": str(100 + i), "displayName": f"Giocatore {a}"},
            "stats": [{"name": "yellowCards", "value": 0}],
        }
        for i, a in enumerate(posizioni, start=1)
    ]
    roster.append({
        "starter": False, "subbedIn": False, "subbedOut": False, "jersey": "21",
        "position": {"abbreviation": "SUB"},
        "athlete": {"id": "200", "displayName": "Panchinaro"},
        "stats": [{"name": "yellowCards", "value": 1}],
    })
    roster.append({  # senza numero
        "starter": False, "subbedIn": False, "subbedOut": False,
        "athlete": {"id": "201", "displayName": "Senza numero"},
        "stats": [{"name": "yellowCards", "value": 0}],
    })
    team = {"id": "2572", "color": "4169E1", "logos": [{"href": LOGO, "rel": ["full", "default"]}]}
    return {"rosters": [{"team": team, "roster": roster}], "keyEvents": []}


@respx.mock
def test_formazioni_con_i_numeri_di_maglia_e_lo_stile(espn):
    respx.get(f"{URL_ESPN}/ita.1/summary").mock(return_value=httpx.Response(200, json=_summary()))
    (f,) = espn.formazioni(1)
    assert f.maglie[101] == 1 and f.maglie[111] == 11 and f.maglie[200] == 21
    assert 201 not in f.maglie
    assert espn.stili_squadre() == {2572: StileSquadra(LOGO, "#4169E1", None)}


@respx.mock
def test_statistiche_con_il_numero_di_maglia(espn):
    respx.get(f"{URL_ESPN}/ita.1/summary").mock(return_value=httpx.Response(200, json=_summary()))
    presenze = {p.giocatore_id: p for p in espn.statistiche(1)}
    assert presenze[107].maglia == 7
    assert presenze[200].maglia == 21 and presenze[200].gialli == 1  # anche dalla panchina
    assert presenze[201].maglia is None
    assert 2572 in espn.stili_squadre()
