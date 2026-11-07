import logging
from datetime import date, datetime
from pathlib import Path

import httpx

from ammonizioni.fonti import designazioni
from ammonizioni.fonti.designazioni import Designazione, designazioni_serie_a, parsa_articolo_aia

DATI = Path(__file__).parent.parent / "dati_prova" / "designazioni"
OGGI = date(2026, 11, 7)

ATTESE = [
    ("VENEZIA", "UDINESE", "SACCHI J.L.", "GARIGLIO", datetime(2026, 11, 6, 20, 45)),
    ("CAGLIARI", "FROSINONE", "AYROLDI", "MARINI", datetime(2026, 11, 7, 15, 0)),
    ("TORINO", "LECCE", "FELICIANI", "MAZZOLENI", datetime(2026, 11, 7, 15, 0)),
    ("PARMA", "BOLOGNA", "ZUFFERLI", "MERAVIGLIA", datetime(2026, 11, 7, 18, 0)),
    ("ROMA", "SASSUOLO", "DI BELLO", "PEZZUTO", datetime(2026, 11, 7, 20, 45)),
    ("NAPOLI", "LAZIO", "PAIRETTO", "AURELIANO", datetime(2026, 11, 8, 12, 30)),
    ("GENOA", "MILAN", "MASSA", "CAMPLONE", datetime(2026, 11, 8, 15, 0)),
    ("MONZA", "ATALANTA", "ALLEGRETTA", "LA PENNA", datetime(2026, 11, 8, 15, 0)),
    ("INTER", "COMO", "CHIFFI", "PATERNA", datetime(2026, 11, 8, 18, 0)),
    ("FIORENTINA", "JUVENTUS", "COLOMBO", "DI PAOLO", datetime(2026, 11, 8, 20, 45)),
]


def leggi(nome: str) -> str:
    return (DATI / nome).read_text(encoding="utf-8")


def client_finto(risposte: dict[str, str | int]) -> httpx.Client:
    """Client che risponde in base all'URL completo; gli URL assenti danno 404."""

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        valore = risposte.get(str(richiesta.url))
        if valore is None:
            return httpx.Response(404)
        if isinstance(valore, int):
            return httpx.Response(valore)
        return httpx.Response(200, text=valore)

    return httpx.Client(transport=httpx.MockTransport(gestore))


URL_POST = "https://www.aia-figc.it/dettaglio.asp?ID=28822"


def test_parser_sulle_dieci_partite_della_11a_giornata():
    trovate = parsa_articolo_aia(leggi("aia_serie_a_11a_giornata.html"), OGGI)
    assert [(d.casa, d.trasferta, d.arbitro) for d in trovate] == [
        (c, t, a) for c, t, a, _, _ in ATTESE
    ]
    assert [d.var for d in trovate] == [v for _, _, _, v, _ in ATTESE]


def test_parser_data_e_ora_locali():
    trovate = {d.casa: d for d in parsa_articolo_aia(leggi("aia_serie_a_11a_giornata.html"), OGGI)}
    assert trovate["VENEZIA"].data_ora_locale == datetime(2026, 11, 6, 20, 45)
    assert trovate["TORINO"].data_ora_locale == datetime(2026, 11, 7, 15, 0)  # "h.15.00"
    assert trovate["NAPOLI"].data_ora_locale == datetime(2026, 11, 8, 12, 30)
    assert trovate["FIORENTINA"].data_ora_locale == datetime(2026, 11, 8, 20, 45)


def test_parser_anno_successivo_per_una_data_di_gennaio():
    html = (
        "<p><strong>INTER &ndash; COMO</strong> <em>Domenica 10/1 h. 18.00</em></p>"
        "<p>CHIFFI</p><p>A &ndash; B</p>"
    )
    d = parsa_articolo_aia(html, date(2026, 12, 28))[0]
    assert d.data_ora_locale == datetime(2027, 1, 10, 18, 0)


def test_serie_a_dall_indice_all_articolo():
    client = client_finto(
        {
            designazioni.URL_INDICE_AIA: leggi("aia_indice_can.html"),
            URL_POST: leggi("aia_serie_a_11a_giornata.html"),
        }
    )
    trovate = designazioni_serie_a(client, OGGI)
    assert len(trovate) == 10
    assert Designazione(
        "INTER", "COMO", datetime(2026, 11, 8, 18, 0), "CHIFFI", "PATERNA"
    ) in trovate


def test_variazione_piu_recente_vince_sull_originale():
    indice = (
        '<a href="/news/variazione-1/">SERIE A ENILIVE - VARIAZIONE DESIGNAZIONI 11a GIORNATA</a>'
        '<a href="/news/base/">SERIE A ENILIVE - DESIGNAZIONI 11a GIORNATA</a>'
        '<a href="/news/b/">SERIE BKT DESIGNAZIONI 11A GIORNATA</a>'
    )
    var = "<p>INTER &ndash; COMO <em>Domenica 8/11 h. 18.00</em></p><p>MARESCA</p>"
    base = "<p>INTER &ndash; COMO <em>Domenica 8/11 h. 18.00</em></p><p>CHIFFI</p>"
    client = client_finto(
        {
            designazioni.URL_INDICE_AIA: indice,
            "https://www.aia-figc.it/news/variazione-1/": var,
            "https://www.aia-figc.it/news/base/": base,
        }
    )
    assert [d.arbitro for d in designazioni_serie_a(client, OGGI)] == ["MARESCA"]


def test_senza_indice_si_prova_la_home():
    home = '<h2><a href="/news/x-28822/">SERIE A ENILIVE - DESIGNAZIONI 11a GIORNATA</a></h2>'
    client = client_finto(
        {
            designazioni.URL_INDICE_AIA: 500,
            designazioni.URL_HOME_AIA: home,
            "https://www.aia-figc.it/news/x-28822/": leggi("aia_serie_a_11a_giornata.html"),
        }
    )
    assert len(designazioni_serie_a(client, OGGI)) == 10


def test_html_rotto_restituisce_lista_vuota_con_avviso(caplog):
    caplog.set_level(logging.WARNING)
    client = client_finto(
        {
            designazioni.URL_INDICE_AIA: leggi("aia_indice_can.html"),
            URL_POST: "<html><body><div>struttura completamente diversa</div></body></html>",
        }
    )
    assert designazioni_serie_a(client, OGGI) == []
    assert "nessuna partita riconosciuta" in caplog.text


def test_indice_senza_articoli_restituisce_lista_vuota_con_avviso(caplog):
    caplog.set_level(logging.WARNING)
    client = client_finto({designazioni.URL_INDICE_AIA: "<html>vuoto</html>",
                           designazioni.URL_HOME_AIA: "<html>vuoto</html>"})
    assert designazioni_serie_a(client, OGGI) == []
    assert "nessun articolo di designazioni di Serie A" in caplog.text


def test_sito_non_raggiungibile_non_solleva(caplog):
    caplog.set_level(logging.WARNING)

    def guasto(richiesta):
        raise httpx.ConnectError("rete assente")

    client = httpx.Client(transport=httpx.MockTransport(guasto))
    assert designazioni_serie_a(client, OGGI) == []
    assert "non letta" in caplog.text


def test_parser_blocco_senza_arbitro_viene_saltato(caplog):
    caplog.set_level(logging.WARNING)
    html = (
        "<p>INTER &ndash; COMO <em>Domenica 8/11 h. 18.00</em></p><p>A &ndash; B</p>"
        "<p>GENOA &ndash; MILAN <em>Domenica 8/11 h. 15.00</em></p><p>MASSA</p>"
    )
    assert [d.arbitro for d in parsa_articolo_aia(html, OGGI)] == ["MASSA"]
    assert "arbitro non leggibile" in caplog.text
