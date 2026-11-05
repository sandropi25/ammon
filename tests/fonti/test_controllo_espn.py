import json
from pathlib import Path

import httpx
import pytest
import respx

from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.controllo_espn import PARTITA_CONTROLLO, controlla_struttura
from ammonizioni.fonti.espn import URL_ESPN, Espn

DATI = Path(__file__).parent.parent / "dati_prova" / "espn"


def riepilogo():
    return json.loads((DATI / "summary_sassuolo_fiorentina.json").read_text(encoding="utf-8"))


class FonteSummary:
    """Fonte finta: restituisce (o solleva) la risposta grezza data."""

    def __init__(self, corpo):
        self.corpo = corpo
        self.chiesti = []

    def summary(self, partita_id):
        self.chiesti.append(partita_id)
        if isinstance(self.corpo, Exception):
            raise self.corpo
        return self.corpo


def giocatori(corpo):
    return [g for r in corpo["rosters"] for g in r["roster"]]


def test_la_partita_di_controllo_e_quella_della_fixture():
    assert PARTITA_CONTROLLO == 401874963


def test_struttura_attuale_senza_problemi():
    fonte = FonteSummary(riepilogo())
    assert controlla_struttura(fonte) == []
    assert fonte.chiesti == [PARTITA_CONTROLLO]


@pytest.mark.parametrize("nome", ["foulsCommitted", "foulsSuffered", "yellowCards", "redCards"])
def test_statistica_mancante_segnalata_con_il_nome(nome):
    corpo = riepilogo()
    for g in giocatori(corpo):
        g["stats"] = [s for s in g["stats"] if s["name"] != nome]
    problemi = controlla_struttura(FonteSummary(corpo))
    assert len(problemi) == 1 and nome in problemi[0]


def test_statistica_mancante_a_un_solo_giocatore():
    corpo = riepilogo()
    g = giocatori(corpo)[0]
    g["stats"] = [s for s in g["stats"] if s["name"] != "foulsCommitted"]
    problemi = controlla_struttura(FonteSummary(corpo))
    assert len(problemi) == 1 and "foulsCommitted" in problemi[0] and "1 giocatori" in problemi[0]


def test_stats_assente_segnalato():
    corpo = riepilogo()
    del giocatori(corpo)[0]["stats"]
    assert any("stats" in p for p in controlla_struttura(FonteSummary(corpo)))


def test_posizione_e_id_mancanti():
    corpo = riepilogo()
    titolare = next(g for g in giocatori(corpo) if g["starter"])
    del titolare["position"]
    altro = next(g for g in giocatori(corpo) if g is not titolare)
    del altro["athlete"]["id"]
    problemi = controlla_struttura(FonteSummary(corpo))
    assert any("position.abbreviation" in p for p in problemi)
    assert any("athlete.id" in p for p in problemi)


def test_nessun_titolare():
    corpo = riepilogo()
    for g in giocatori(corpo):
        g.pop("starter", None)
    assert any("titolare" in p for p in controlla_struttura(FonteSummary(corpo)))


def test_rosters_assente():
    corpo = riepilogo()
    del corpo["rosters"]
    assert controlla_struttura(FonteSummary(corpo)) == ["manca 'rosters'"]


def test_key_events_senza_minuto():
    corpo = riepilogo()
    for e in corpo["keyEvents"]:
        e.pop("clock", None)
    assert any("clock" in p for p in controlla_struttura(FonteSummary(corpo)))
    del corpo["keyEvents"]
    assert any("keyEvents" in p for p in controlla_struttura(FonteSummary(corpo)))


def test_lettura_fallita_e_un_problema_non_un_errore():
    problemi = controlla_struttura(FonteSummary(ErroreFonte("HTTP 404")))
    assert len(problemi) == 1 and "HTTP 404" in problemi[0]


@respx.mock
def test_con_espn_reale_via_http_finto():
    respx.get(f"{URL_ESPN}/ita.1/summary", params={"event": PARTITA_CONTROLLO}).mock(
        return_value=httpx.Response(200, json=riepilogo())
    )
    with httpx.Client() as client:
        assert controlla_struttura(Espn(client=client)) == []
