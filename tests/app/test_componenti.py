from datetime import datetime, timezone
from types import SimpleNamespace

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import componenti


def test_data_italiana_usa_europe_rome():
    # 8 novembre 2026: ora solare (UTC+1)
    assert componenti.data_italiana(datetime(2026, 11, 8, 19, 45, tzinfo=timezone.utc)) == "dom 08/11 20:45"
    # estate: UTC+2
    assert componenti.data_italiana(datetime(2026, 8, 22, 18, 45, tzinfo=timezone.utc)) == "sab 22/08 20:45"


def test_percentuale():
    assert componenti.percentuale(0.344) == "34%"
    assert componenti.percentuale(0.02) == "2%"


def test_link_sofascore():
    con = SimpleNamespace(nome="Mario Rossi", sofascore_url="https://www.sofascore.com/x")
    senza = SimpleNamespace(nome="Mario Rossi", sofascore_url=None)
    assert componenti.link_sofascore(con) == "https://www.sofascore.com/x"
    assert componenti.link_sofascore(senza) == "https://www.google.com/search?q=sofascore+Mario+Rossi"


def test_link_esterni_tutte_le_app_in_ordine():
    g = SimpleNamespace(nome="Mario Rossi", sofascore_url=None)
    link = componenti.link_esterni(g)
    assert [nome for nome, _ in link] == [
        "Sofascore", "FBref", "FotMob", "WhoScored", "Transfermarkt", "Diretta",
    ]
    url = dict(link)
    assert url["Sofascore"] == "https://www.google.com/search?q=sofascore+Mario+Rossi"
    assert url["FBref"] == "https://fbref.com/search/search.fcgi?search=Mario+Rossi"
    assert url["Transfermarkt"] == (
        "https://www.transfermarkt.it/schnellsuche/ergebnis/schnellsuche?query=Mario+Rossi"
    )
    assert url["FotMob"] == "https://www.google.com/search?q=site%3Afotmob.com+Mario+Rossi"
    assert url["WhoScored"] == "https://www.google.com/search?q=site%3Awhoscored.com+Mario+Rossi"
    assert url["Diretta"] == "https://www.google.com/search?q=site%3Adiretta.it+Mario+Rossi"


def test_link_esterni_codifica_nomi_con_accenti():
    g = SimpleNamespace(nome="Hakan Çalhanoğlu", sofascore_url="https://www.sofascore.com/x")
    url = dict(componenti.link_esterni(g))
    assert url["Sofascore"] == "https://www.sofascore.com/x"
    assert url["FBref"] == "https://fbref.com/search/search.fcgi?search=Hakan+%C3%87alhano%C4%9Flu"
