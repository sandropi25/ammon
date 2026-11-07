import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from ammonizioni.caricamento import designazioni as modulo
from ammonizioni.caricamento.arbitri import trova_o_crea
from ammonizioni.caricamento.arbitri_fd import stessa_squadra
from ammonizioni.caricamento.designazioni import (
    CHIAVE_ULTIMO,
    collega_designazioni,
    collega_designazioni_periodico,
    nome_arbitro,
)
from ammonizioni.db import repo
from ammonizioni.db.modelli import Arbitro, Partita, Squadra
from ammonizioni.fonti import designazioni as fonte

DATI = Path(__file__).parent.parent / "dati_prova" / "designazioni"
ADESSO = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

# Le 20 squadre di Serie A 2025-26 come le scrive l'AIA, con il nome ESPN nel database.
SQUADRE_AIA = [
    ("ATALANTA", "Atalanta"), ("BOLOGNA", "Bologna"), ("CAGLIARI", "Cagliari"),
    ("COMO", "Como"), ("CREMONESE", "Cremonese"), ("FIORENTINA", "Fiorentina"),
    ("GENOA", "Genoa"), ("HELLAS VERONA", "Hellas Verona"), ("INTER", "Internazionale"),
    ("JUVENTUS", "Juventus"), ("LAZIO", "Lazio"), ("LECCE", "Lecce"), ("MILAN", "AC Milan"),
    ("NAPOLI", "Napoli"), ("PARMA", "Parma"), ("PISA", "Pisa"), ("ROMA", "AS Roma"),
    ("SASSUOLO", "Sassuolo"), ("TORINO", "Torino"), ("UDINESE", "Udinese"),
]


@pytest.mark.parametrize("aia,espn", SQUADRE_AIA, ids=[a for a, _ in SQUADRE_AIA])
def test_le_venti_squadre_di_serie_a_come_le_scrive_l_aia(aia, espn):
    assert stessa_squadra(aia, espn)


def test_squadre_aia_senza_confusioni():
    for i, (aia, _) in enumerate(SQUADRE_AIA):
        for j, (_, espn) in enumerate(SQUADRE_AIA):
            assert stessa_squadra(aia, espn) == (i == j)


def test_squadre_aia_anche_con_i_nomi_di_football_data():
    assert stessa_squadra("INTER", "FC Internazionale Milano")
    assert stessa_squadra("HELLAS VERONA", "Hellas Verona FC")
    assert stessa_squadra("ROMA", "AS Roma")
    assert stessa_squadra("MILAN", "AC Milan")


@pytest.mark.parametrize(
    "grezzo,atteso",
    [("SACCHI J.L.", "Sacchi"), ("DI BELLO", "Di Bello"), ("ROSSI L.", "Rossi"), ("MASSA", "Massa")],
)
def test_nome_arbitro(grezzo, atteso):
    assert nome_arbitro(grezzo) == atteso


# --- collegamento -------------------------------------------------------------


def _articolo(blocchi: list[tuple[str, str, str]]) -> str:
    return "".join(
        f"<p><strong>{c} &ndash; {t}</strong> <em>Sabato 7/11 h. 15.00</em></p>"
        f"<p>{a}</p><p>X &ndash; Y</p><p>VAR: Z</p>"
        for c, t, a in blocchi
    )


def client_con(blocchi) -> httpx.Client:
    pagine = {
        fonte.URL_INDICE_AIA: '<a href="/news/a/">SERIE A ENILIVE - DESIGNAZIONI 11a GIORNATA</a>',
        "https://www.aia-figc.it/news/a/": _articolo(blocchi),
    }

    def gestore(r):
        testo = pagine.get(str(r.url))
        return httpx.Response(404) if testo is None else httpx.Response(200, text=testo)

    return httpx.Client(transport=httpx.MockTransport(gestore))


def aggiungi(s, id, casa, trasferta, data, arbitro_id=None, competizione_id=135, stato="NS"):
    for sid, nome in (casa, trasferta):
        if s.get(Squadra, sid) is None:
            s.add(Squadra(id=sid, nome=nome))
    s.flush()
    s.add(
        Partita(
            id=id, data_utc=data, competizione_id=competizione_id, stagione=2026,
            casa_id=casa[0], trasferta_id=trasferta[0], arbitro_id=arbitro_id, stato=stato,
        )
    )
    s.flush()


INTER = (1, "Internazionale")
COMO = (2, "Como")
MILAN = (3, "AC Milan")
GENOA = (4, "Genoa")
DOMANI = ADESSO + timedelta(days=3)


def arbitro_di(s, id) -> str | None:
    p = s.get(Partita, id)
    return None if p.arbitro_id is None else s.get(Arbitro, p.arbitro_id).nome_visualizzato


def test_designazione_riempie_l_arbitro_mancante(sessione):
    aggiungi(sessione, 1, INTER, COMO, DOMANI)
    assert collega_designazioni(sessione, client_con([("INTER", "COMO", "CHIFFI")]), ADESSO) == 1
    assert arbitro_di(sessione, 1) == "Chiffi"


def test_nome_con_iniziali_diventa_il_cognome(sessione):
    aggiungi(sessione, 1, INTER, COMO, DOMANI)
    collega_designazioni(sessione, client_con([("INTER", "COMO", "SACCHI J.L.")]), ADESSO)
    assert arbitro_di(sessione, 1) == "Sacchi"


def test_di_bello_e_la_stessa_riga_di_marco_di_bello_di_football_data(sessione):
    esistente = trova_o_crea(sessione, "Marco Di Bello", 135)
    aggiungi(sessione, 1, INTER, COMO, DOMANI)
    collega_designazioni(sessione, client_con([("INTER", "COMO", "DI BELLO")]), ADESSO)
    assert sessione.get(Partita, 1).arbitro_id == esistente.id
    assert sessione.query(Arbitro).count() == 1
    assert arbitro_di(sessione, 1) == "Marco Di Bello"


def test_variazione_corregge_l_arbitro_provvisorio(sessione):
    provvisorio = trova_o_crea(sessione, "Massa", 135)
    aggiungi(sessione, 1, INTER, COMO, DOMANI, arbitro_id=provvisorio.id)
    assert collega_designazioni(sessione, client_con([("INTER", "COMO", "CHIFFI")]), ADESSO) == 1
    assert arbitro_di(sessione, 1) == "Chiffi"


def test_stesso_arbitro_non_conta_come_modifica(sessione):
    chiffi = trova_o_crea(sessione, "Chiffi", 135)
    aggiungi(sessione, 1, INTER, COMO, DOMANI, arbitro_id=chiffi.id)
    assert collega_designazioni(sessione, client_con([("INTER", "COMO", "CHIFFI")]), ADESSO) == 0


def test_senza_designazioni_non_si_cancella_nulla(sessione):
    chiffi = trova_o_crea(sessione, "Chiffi", 135)
    aggiungi(sessione, 1, INTER, COMO, DOMANI, arbitro_id=chiffi.id)
    assert collega_designazioni(sessione, client_con([]), ADESSO) == 0
    assert sessione.get(Partita, 1).arbitro_id == chiffi.id


def test_non_tocca_partite_gia_iniziate_o_finite(sessione):
    aggiungi(sessione, 1, INTER, COMO, ADESSO - timedelta(hours=1))
    aggiungi(sessione, 2, MILAN, GENOA, ADESSO - timedelta(days=5), stato="FT")
    n = collega_designazioni(
        sessione, client_con([("INTER", "COMO", "CHIFFI"), ("MILAN", "GENOA", "MASSA")]), ADESSO
    )
    assert n == 0
    assert arbitro_di(sessione, 1) is None and arbitro_di(sessione, 2) is None


def test_casa_e_trasferta_invertite_non_collegano(sessione):
    aggiungi(sessione, 1, COMO, INTER, DOMANI)
    assert collega_designazioni(sessione, client_con([("INTER", "COMO", "CHIFFI")]), ADESSO) == 0


def test_solo_serie_a(sessione):
    aggiungi(sessione, 1, INTER, COMO, DOMANI, competizione_id=140)
    assert collega_designazioni(sessione, client_con([("INTER", "COMO", "CHIFFI")]), ADESSO) == 0


def test_partita_senza_designazione_resta_com_e(sessione):
    aggiungi(sessione, 1, MILAN, GENOA, DOMANI)
    assert collega_designazioni(sessione, client_con([("INTER", "COMO", "CHIFFI")]), ADESSO) == 0
    assert arbitro_di(sessione, 1) is None


def test_fixture_reali_undici_giornata(sessione):
    """Articolo reale dell'AIA (11a giornata) su un database con le dieci partite."""
    coppie = [
        ("Venezia", "Udinese"), ("Cagliari", "Frosinone"), ("Torino", "Lecce"),
        ("Parma", "Bologna"), ("AS Roma", "Sassuolo"), ("Napoli", "Lazio"), ("Genoa", "AC Milan"),
        ("AC Monza", "Atalanta"), ("Internazionale", "Como"), ("Fiorentina", "Juventus"),
    ]
    for i, (c, t) in enumerate(coppie):
        aggiungi(sessione, i + 1, (100 + 2 * i, c), (101 + 2 * i, t), DOMANI + timedelta(hours=i))
    pagine = {
        fonte.URL_INDICE_AIA: (DATI / "aia_indice_can.html").read_text(encoding="utf-8"),
        "https://www.aia-figc.it/dettaglio.asp?ID=28822": (
            DATI / "aia_serie_a_11a_giornata.html"
        ).read_text(encoding="utf-8"),
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text=pagine[str(r.url)])
            if str(r.url) in pagine
            else httpx.Response(404)
        )
    )
    assert collega_designazioni(sessione, client, ADESSO) == 10
    assert [arbitro_di(sessione, i) for i in range(1, 11)] == [
        "Sacchi", "Ayroldi", "Feliciani", "Zufferli", "Di Bello",
        "Pairetto", "Massa", "Allegretta", "Chiffi", "Colombo",
    ]


# --- periodico (al massimo ogni 3 ore) ------------------------------------------


class ClientContato:
    def __init__(self, blocchi):
        self.interno = client_con(blocchi)
        self.richieste = 0

    def get(self, url, **kw):
        self.richieste += 1
        return self.interno.get(url, **kw)


def test_periodico_scrive_il_momento_e_aspetta_tre_ore(sessione):
    aggiungi(sessione, 1, INTER, COMO, DOMANI)
    client = ClientContato([("INTER", "COMO", "CHIFFI")])
    assert collega_designazioni_periodico(sessione, ADESSO, client) == 1
    assert repo.leggi_impostazione(sessione, CHIAVE_ULTIMO) == ADESSO.isoformat()
    richieste = client.richieste
    assert richieste > 0
    aggiungi(sessione, 2, MILAN, GENOA, DOMANI)
    client2 = ClientContato([("MILAN", "GENOA", "MASSA")])
    assert collega_designazioni_periodico(
        sessione, ADESSO + timedelta(hours=2, minutes=59), client2
    ) == 0
    assert client2.richieste == 0  # nessuna richiesta
    assert collega_designazioni_periodico(sessione, ADESSO + timedelta(hours=3), client2) == 1
    assert client2.richieste > 0


def test_periodico_errore_non_solleva_e_non_si_riprova_subito(sessione, caplog):
    caplog.set_level(logging.WARNING)

    class Guasto:
        def get(self, url, **kw):
            raise RuntimeError("esploso")

    assert collega_designazioni_periodico(sessione, ADESSO, Guasto()) == 0
    assert repo.leggi_impostazione(sessione, CHIAVE_ULTIMO) == ADESSO.isoformat()


def test_periodico_usa_il_client_di_default_senza_rete(sessione):
    # la fixture autouse sostituisce crea_client con un client che risponde 503
    assert modulo.crea_client().get("https://www.aia-figc.it/").status_code == 503
    assert collega_designazioni_periodico(sessione, ADESSO) == 0
