"""Ricerca delle foto su TheSportsDB con un trasporto httpx finto (nessuna rete)."""
from datetime import date

import httpx
import pytest

from ammonizioni.fonti import foto
from ammonizioni.fonti.foto import LimiteFoto, cerca_foto

CUTOUT = "https://r2.thesportsdb.com/images/media/player/cutout/mina.png"
THUMB = "https://r2.thesportsdb.com/images/media/player/thumb/mina.jpg"


def p(nome, **campi):
    base = {"strPlayer": nome, "strSport": "Soccer", "strTeam": "Cagliari",
            "dateBorn": "1994-09-23", "strCutout": CUTOUT, "strThumb": THUMB}
    base.update(campi)
    return base


def client(risposte, richieste=None):
    """risposte: nome cercato -> elenco di giocatori (None = player null) o httpx.Response."""
    def gestore(richiesta):
        nome = richiesta.url.params["p"]
        if richieste is not None:
            richieste.append(nome)
        voce = risposte.get(nome)
        if isinstance(voce, httpx.Response):
            return voce
        return httpx.Response(200, json={"player": voce})
    return foto.ClientFoto(transport=httpx.MockTransport(gestore), pausa=0)


def test_trova_il_ritaglio():
    assert cerca_foto(client({"Yerry Mina": [p("Yerry Mina")]}), "Yerry Mina") == CUTOUT


def test_senza_ritaglio_usa_la_miniatura():
    c = client({"Yerry Mina": [p("Yerry Mina", strCutout=None)]})
    assert cerca_foto(c, "Yerry Mina") == THUMB


def test_nessun_risultato():
    assert cerca_foto(client({"Yerry Mina": None}), "Yerry Mina") is None


def test_riprova_senza_accenti():
    richieste = []
    c = client({"Nicolo Zaniolo": [p("Nicolo Zaniolo")]}, richieste)
    assert cerca_foto(c, "Nicolò Zaniolo") == CUTOUT
    assert richieste == ["Nicolò Zaniolo", "Nicolo Zaniolo"]


def test_nome_con_accento_trovato_subito_non_riprova():
    richieste = []
    c = client({"Nicolò Zaniolo": [p("Nicolò Zaniolo")]}, richieste)
    assert cerca_foto(c, "Nicolò Zaniolo") == CUTOUT
    assert richieste == ["Nicolò Zaniolo"]


def test_accenti_e_maiuscole_indifferenti_nel_confronto():
    c = client({"Alex Baena": [p("ÁLEX BAENA")]})
    assert cerca_foto(c, "Alex Baena") == CUTOUT


def test_cognome_diverso_rifiutato():
    c = client({"Yerry Mina": [p("Yerry Pinto")]})
    assert cerca_foto(c, "Yerry Mina") is None


def test_non_calcio_rifiutato():
    c = client({"Yerry Mina": [p("Yerry Mina", strSport="Basketball")]})
    assert cerca_foto(c, "Yerry Mina") is None


@pytest.mark.parametrize("url", [
    "http://r2.thesportsdb.com/a.png", "https://example.com/a.png",
    "https://r2.thesportsdb.com.evil.net/a.png", "javascript:alert(1)",
])
def test_host_o_schema_non_ammesso(url):
    c = client({"Yerry Mina": [p("Yerry Mina", strCutout=url, strThumb=url)]})
    assert cerca_foto(c, "Yerry Mina") is None


def test_cutout_cattivo_ripiega_sulla_miniatura_buona():
    c = client({"Yerry Mina": [p("Yerry Mina", strCutout="https://example.com/a.png")]})
    assert cerca_foto(c, "Yerry Mina") == THUMB


def test_omonimi_si_sceglie_con_la_data_di_nascita():
    altro = p("Yerry Mina", dateBorn="2001-01-01", strCutout="https://r2.thesportsdb.com/x.png")
    c = client({"Yerry Mina": [altro, p("Yerry Mina")]})
    assert cerca_foto(c, "Yerry Mina", data_nascita=date(1994, 9, 23)) == CUTOUT


def test_data_diversa_dall_unico_candidato_lo_scarta():
    c = client({"Yerry Mina": [p("Yerry Mina", dateBorn="2001-01-01")]})
    assert cerca_foto(c, "Yerry Mina", data_nascita=date(1994, 9, 23)) is None


def test_omonimi_si_sceglie_con_la_squadra():
    altro = p("Yerry Mina", dateBorn=None, strTeam="Palermo",
              strCutout="https://r2.thesportsdb.com/x.png")
    mio = p("Yerry Mina", dateBorn=None, strTeam="Cagliari Calcio")
    c = client({"Yerry Mina": [altro, mio]})
    assert cerca_foto(c, "Yerry Mina", squadra="Cagliari") == CUTOUT


def test_omonimi_ambigui_nessuna_foto():
    c = client({"Yerry Mina": [p("Yerry Mina", dateBorn=None), p("Yerry Mina", dateBorn=None)]})
    assert cerca_foto(c, "Yerry Mina") is None


def test_429_solleva_il_segnale_di_stop():
    c = client({"Yerry Mina": httpx.Response(429)})
    with pytest.raises(LimiteFoto):
        cerca_foto(c, "Yerry Mina")


def test_errori_di_rete_e_json_danno_none(caplog):
    def rotto(richiesta):
        raise httpx.ConnectError("giù")
    c = foto.ClientFoto(transport=httpx.MockTransport(rotto), pausa=0)
    assert cerca_foto(c, "Yerry Mina") is None
    assert cerca_foto(client({"Yerry Mina": httpx.Response(200, text="<html>")}), "Yerry Mina") is None
    assert cerca_foto(client({"Yerry Mina": httpx.Response(500)}), "Yerry Mina") is None
    assert cerca_foto(client({}), "") is None


def test_pausa_tra_le_richieste():
    attese, ora = [], [100.0]
    c = foto.ClientFoto(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"player": None})),
        pausa=2.2, attesa=attese.append, orologio=lambda: ora[0],
    )
    c.get(foto.URL_RICERCA, params={"p": "a"})
    ora[0] += 0.5
    c.get(foto.URL_RICERCA, params={"p": "b"})
    assert len(attese) == 1 and attese[0] == pytest.approx(1.7)
    assert c.headers["User-Agent"] == "ammonizioni/1.0 (uso personale)"
