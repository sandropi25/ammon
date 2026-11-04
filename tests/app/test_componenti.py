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
