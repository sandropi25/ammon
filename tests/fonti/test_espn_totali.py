"""Cartellini e falli totali di partita dal tabellone ESPN (eventi `details`)."""
import httpx
import pytest
import respx

from ammonizioni.fonti.espn import URL_ESPN, Espn, cartellini_tabellone, falli_tabellone


def _evento(testo, squadra="1", **extra):
    return {
        "type": {"id": "94", "text": testo},
        "clock": {"value": 2400.0, "displayValue": "40'"},
        "team": {"id": squadra},
        **extra,
    }


def _competizione(details="assente", falli=(10, 12)):
    competitori = []
    for lato, valore in zip(("home", "away"), falli):
        c = {"homeAway": lato, "score": "1", "team": {"id": "1" if lato == "home" else "2",
                                                       "displayName": lato}}
        if valore is not None:
            c["statistics"] = [
                {"name": "possessionPct", "displayValue": "50"},
                {"name": "foulsCommitted", "displayValue": str(valore)},
            ]
        competitori.append(c)
    comp = {"id": "9", "competitors": competitori}
    if details != "assente":
        comp["details"] = details
    return comp


def test_gialli_e_rossi_dal_tabellone():
    comp = _competizione([
        _evento("Goal"), _evento("Yellow Card"), _evento("Yellow Card", "2"),
        _evento("Red Card", "2"), _evento("Substitution"),
    ])
    assert cartellini_tabellone(comp) == (2, 1)


def test_secondo_giallo_come_lo_riporta_espn_giallo_piu_rosso():
    # ESPN: il secondo giallo compare come un cartellino giallo e uno rosso
    comp = _competizione([
        _evento("Yellow Card"), _evento("Yellow Card"), _evento("Red Card"),
    ])
    assert cartellini_tabellone(comp) == (2, 1)


def test_partita_senza_cartellini_vale_zero_ma_details_assente_e_sconosciuto():
    assert cartellini_tabellone(_competizione([_evento("Goal")])) == (0, 0)
    assert cartellini_tabellone(_competizione([])) == (0, 0)
    assert cartellini_tabellone(_competizione()) is None


def test_evento_senza_tipo_usa_i_segnalibri():
    comp = _competizione([{"yellowCard": True}, {"redCard": True}, {"yellowCard": False}, "x"])
    assert cartellini_tabellone(comp) == (1, 1)


def test_falli_somma_delle_due_squadre():
    assert falli_tabellone(_competizione([], falli=(10, 12))) == 22


def test_falli_mancanti_se_una_squadra_non_li_ha():
    assert falli_tabellone(_competizione([], falli=(10, None))) is None


def _evento_partita(id_, data, stato, details):
    return {
        "id": str(id_), "date": data,
        "status": {"type": {"name": stato}},
        "competitions": [dict(
            _competizione(details),
            id=str(id_),
            competitors=[
                {"homeAway": "home", "score": "2", "team": {"id": "1", "displayName": "A"},
                 "statistics": [{"name": "foulsCommitted", "displayValue": "11"}]},
                {"homeAway": "away", "score": "1", "team": {"id": "2", "displayName": "B"},
                 "statistics": [{"name": "foulsCommitted", "displayValue": "9"}]},
            ],
        )],
    }


@pytest.fixture
def espn():
    with httpx.Client() as client:
        yield Espn(None, client=client, dormi=lambda s: None)


@respx.mock
def test_partite_2023_portano_i_totali_solo_se_finite(espn):
    finita = _evento_partita(
        1, "2023-09-02T18:45Z", "STATUS_FULL_TIME",
        [_evento("Yellow Card"), _evento("Yellow Card"), _evento("Red Card")],
    )
    futura = _evento_partita(2, "2024-05-02T18:45Z", "STATUS_SCHEDULED", [])
    for anno, eventi in (("2023", [finita]), ("2024", [futura])):
        respx.get(f"{URL_ESPN}/ita.1/scoreboard", params={"dates": anno, "limit": "1000"}).mock(
            return_value=httpx.Response(200, json={"events": eventi})
        )
    partite = {p.id: p for p in espn.partite(135, 2023)}
    assert (partite[1].gialli_totali, partite[1].rossi_totali, partite[1].falli_totali) == (2, 1, 20)
    assert (partite[2].gialli_totali, partite[2].rossi_totali, partite[2].falli_totali) == (
        None, None, None,
    )
