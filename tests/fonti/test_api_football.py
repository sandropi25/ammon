import json
from datetime import timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from ammonizioni.config import URL_API
from ammonizioni.fonti.api_football import ApiFootball, _giornata
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.limite import LimiteRichieste, LimiteSuperato, Priorita

DATI = Path(__file__).parent.parent / "dati_prova" / "api"


def carica(nome):
    return json.loads((DATI / nome).read_text(encoding="utf-8"))


@pytest.fixture
def attese():
    return []


@pytest.fixture
def api(sessione, attese):
    limite = LimiteRichieste(sessione, dormi=lambda s: None)
    with httpx.Client() as client:
        yield ApiFootball("chiave-prova", limite, client=client, dormi=attese.append)


@pytest.mark.parametrize(
    "testo, atteso",
    [
        ("Regular Season - 12", 12),
        ("League Stage - 3", 3),
        ("Round of 16", None),
        ("Round of 32", None),
        ("Round of 64", None),
        ("Quarter-finals", None),
        (None, None),
    ],
)
def test_giornata_solo_formato_campionato(testo, atteso):
    assert _giornata(testo) == atteso


@respx.mock
def test_partite_conversione(api):
    rotta = respx.get(f"{URL_API}/fixtures").mock(
        return_value=httpx.Response(200, json=carica("fixtures_lista.json"))
    )
    partite = api.partite(135, 2026)
    assert dict(rotta.calls.last.request.url.params) == {"league": "135", "season": "2026"}
    assert rotta.calls.last.request.headers["x-apisports-key"] == "chiave-prova"
    assert len(partite) == 2
    p = partite[0]
    assert (p.id, p.competizione_id, p.stagione, p.giornata) == (900001, 135, 2026, 1)
    assert (p.casa_id, p.casa_nome, p.trasferta_id, p.trasferta_nome) == (
        505, "Inter", 489, "AC Milan",
    )
    assert p.arbitro_nome == "Daniele Doveri, Italy"
    assert (p.gol_casa, p.gol_trasferta, p.stato) == (2, 1, "FT")
    assert p.data_utc.utcoffset() == timedelta(0)
    assert p.data_utc.tzinfo is not None


@respx.mock
def test_data_con_offset_convertita_in_utc(api):
    respx.get(f"{URL_API}/fixtures").mock(
        return_value=httpx.Response(200, json=carica("fixtures_lista.json"))
    )
    p = api.partite(135, 2026)[1]
    assert p.data_utc.tzinfo == timezone.utc
    assert (p.data_utc.hour, p.data_utc.minute) == (18, 45)  # 20:45+02:00
    assert p.arbitro_nome is None
    assert p.gol_casa is None and p.gol_trasferta is None
    assert p.stato == "NS"


@respx.mock
def test_partita_rinviata_stato_PST(api):
    rotta = respx.get(f"{URL_API}/fixtures").mock(
        return_value=httpx.Response(200, json=carica("fixture_rinviata.json"))
    )
    p = api.partita(900003)
    assert dict(rotta.calls.last.request.url.params) == {"id": "900003"}
    assert p.stato == "PST"
    assert p.id == 900003


@respx.mock
def test_partita_inesistente_solleva_errore_fonte(api):
    vuota = {"get": "fixtures", "errors": [], "results": 0, "response": []}
    respx.get(f"{URL_API}/fixtures").mock(return_value=httpx.Response(200, json=vuota))
    with pytest.raises(ErroreFonte):
        api.partita(1)


@respx.mock
def test_statistiche_conversione(api):
    rotta = respx.get(f"{URL_API}/fixtures/players").mock(
        return_value=httpx.Response(200, json=carica("fixtures_players.json"))
    )
    stat = api.statistiche(900001)
    assert dict(rotta.calls.last.request.url.params) == {"fixture": "900001"}
    assert len(stat) == 3
    barella = next(x for x in stat if x.giocatore_id == 1001)
    assert barella.giocatore_nome == "N. Barella"
    assert barella.partita_id == 900001
    assert barella.squadra_id == 505
    assert barella.gialli == 1
    assert barella.falli_commessi == 3
    assert barella.falli_subiti == 2
    assert (barella.dribbling_tentati, barella.dribbling_riusciti) == (4, 2)
    assert (barella.tiri, barella.gol, barella.assist) == (2, 1, 0)  # assist null -> 0
    assert (barella.minuti, barella.ruolo, barella.titolare) == (90, "M", True)
    assert barella.voto == 7.1
    assert barella.griglia is None

    sommer = next(x for x in stat if x.giocatore_id == 1002)
    assert sommer.voto is None
    assert (sommer.falli_commessi, sommer.falli_subiti, sommer.tiri, sommer.gol) == (0, 0, 0, 0)
    assert (sommer.dribbling_tentati, sommer.dribbling_riusciti) == (0, 0)

    leao = next(x for x in stat if x.giocatore_id == 2001)
    assert leao.squadra_id == 489
    assert leao.titolare is False
    assert (leao.gialli, leao.rossi, leao.assist, leao.minuti) == (0, 1, 1, 25)
    assert leao.voto == 6.4


@respx.mock
def test_formazioni_conversione(api):
    respx.get(f"{URL_API}/fixtures/lineups").mock(
        return_value=httpx.Response(200, json=carica("fixtures_lineups.json"))
    )
    forma = api.formazioni(900001)
    assert [f.squadra_id for f in forma] == [505, 489]
    assert all(f.partita_id == 900001 for f in forma)
    assert forma[0].titolari == [
        (1002, "Y. Sommer", "G", "1:1"),
        (1001, "N. Barella", "M", "3:2"),
    ]
    assert forma[1].titolari == [(2002, "M. Maignan", "G", None)]


@respx.mock
def test_formazioni_vuote_se_non_uscite(api):
    respx.get(f"{URL_API}/fixtures/lineups").mock(
        return_value=httpx.Response(200, json=carica("lineups_vuote.json"))
    )
    assert api.formazioni(900002) == []


@respx.mock
def test_retry_su_500_poi_successo(api, attese):
    rotta = respx.get(f"{URL_API}/fixtures").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, json=carica("fixtures_lista.json")),
        ]
    )
    assert len(api.partite(135, 2026)) == 2
    assert rotta.call_count == 3
    assert attese == [1, 2]


@respx.mock
def test_retry_su_429_e_errori_di_rete(api, attese):
    respx.get(f"{URL_API}/fixtures").mock(
        side_effect=[
            httpx.Response(429),
            httpx.ConnectError("giù"),
            httpx.Response(200, json=carica("fixtures_lista.json")),
        ]
    )
    assert len(api.partite(135, 2026)) == 2
    assert attese == [1, 2]


LIMITE_AL_MINUTO = {
    "errors": {"rateLimit": "Too many requests. Your rate limit is 10 requests per minute."},
    "response": [],
}


@pytest.mark.parametrize(
    "corpo",
    [
        LIMITE_AL_MINUTO,
        {"errors": ["Too many requests per minute"], "response": []},
    ],
    ids=["chiave_rateLimit", "testo_requests_per_minute"],
)
@respx.mock
def test_limite_al_minuto_nel_corpo_200_ritenta_come_429(api, attese, corpo):
    rotta = respx.get(f"{URL_API}/fixtures").mock(
        side_effect=[
            httpx.Response(200, json=corpo),
            httpx.Response(200, json=carica("fixtures_lista.json")),
        ]
    )
    assert len(api.partite(135, 2026)) == 2
    assert rotta.call_count == 2
    assert attese == [1]


@respx.mock
def test_limite_al_minuto_nel_corpo_retry_esauriti(api, attese):
    rotta = respx.get(f"{URL_API}/fixtures").mock(
        return_value=httpx.Response(200, json=LIMITE_AL_MINUTO)
    )
    with pytest.raises(ErroreFonte, match="rate limit"):
        api.partite(135, 2026)
    assert rotta.call_count == 5
    assert attese == [1, 2, 4, 8]


@respx.mock
def test_retry_esauriti_solleva_errore_fonte(api, attese):
    rotta = respx.get(f"{URL_API}/fixtures").mock(return_value=httpx.Response(503))
    with pytest.raises(ErroreFonte):
        api.partite(135, 2026)
    assert rotta.call_count == 5
    assert attese == [1, 2, 4, 8]


@respx.mock
def test_errore_4xx_non_ritenta(api, attese):
    rotta = respx.get(f"{URL_API}/fixtures").mock(return_value=httpx.Response(404))
    with pytest.raises(ErroreFonte):
        api.partite(135, 2026)
    assert rotta.call_count == 1
    assert attese == []


@respx.mock
def test_errors_nella_risposta_solleva_errore_fonte(api):
    respx.get(f"{URL_API}/fixtures").mock(
        return_value=httpx.Response(200, json=carica("errore_chiave.json"))
    )
    with pytest.raises(ErroreFonte, match="Missing application key"):
        api.partite(135, 2026)


@respx.mock
def test_limite_superato_prima_della_chiamata_http(sessione):
    limite = LimiteRichieste(sessione, max_giorno=1, riserva_oggi=0, dormi=lambda s: None)
    rotta = respx.get(f"{URL_API}/fixtures").mock(
        return_value=httpx.Response(200, json=carica("fixtures_lista.json"))
    )
    with httpx.Client() as client:
        api = ApiFootball("k", limite, client=client, dormi=lambda s: None)
        api.partite(135, 2026)
        with pytest.raises(LimiteSuperato):
            api.partite(135, 2026)
    assert rotta.call_count == 1


@respx.mock
def test_priorita_storico_rispetta_la_riserva(sessione):
    limite = LimiteRichieste(sessione, max_giorno=3, riserva_oggi=1, dormi=lambda s: None)
    respx.get(f"{URL_API}/fixtures").mock(
        return_value=httpx.Response(200, json=carica("fixtures_lista.json"))
    )
    with httpx.Client() as client:
        storico = ApiFootball(
            "k", limite, client=client, priorita=Priorita.STORICO, dormi=lambda s: None
        )
        storico.partite(135, 2026)
        storico.partite(135, 2026)
        with pytest.raises(LimiteSuperato):
            storico.partite(135, 2026)
