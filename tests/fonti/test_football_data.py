import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from ammonizioni import config
from ammonizioni.db import repo
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.football_data import (
    URL_FOOTBALL_DATA,
    ArbitroPartita,
    FootballData,
    stagione_intera,
)
from ammonizioni.fonti.limite import (
    LimiteRichieste,
    LimiteRichiesteLocale,
    LimiteSuperato,
    Priorita,
    crea_limite_football_data,
)

DATI = Path(__file__).parent.parent / "dati_prova" / "football_data"
URL_SA = f"{URL_FOOTBALL_DATA}/competitions/SA/matches"


def corpo():
    return json.loads((DATI / "matches_ridotto.json").read_text(encoding="utf-8"))


@pytest.fixture
def attese():
    return []


@pytest.fixture
def fd(attese):
    with httpx.Client() as client:
        yield FootballData("chiave-segreta", client=client, dormi=attese.append)


# --- stagione intera ---------------------------------------------------------


@pytest.mark.parametrize(
    "dal,al,atteso",
    [
        (date(2025, 7, 1), date(2026, 6, 30), 2025),
        (date(2025, 7, 1), date(2026, 7, 1), 2025),
        (date(2025, 6, 1), date(2026, 7, 31), None),
        (date(2025, 7, 1), date(2026, 7, 31), None),
        (date(2025, 7, 1), date(2026, 6, 29), None),
        (date(2025, 8, 1), date(2026, 6, 30), None),
        (date(2025, 8, 23), date(2025, 8, 23), None),
        (date(2026, 1, 1), date(2026, 12, 31), None),
    ],
)
def test_stagione_intera(dal, al, atteso):
    assert stagione_intera(dal, al) == atteso


# --- richieste ---------------------------------------------------------------


@respx.mock
def test_stagione_intera_una_sola_richiesta_con_season(fd):
    rotta = respx.get(URL_SA).mock(return_value=httpx.Response(200, json=corpo()))
    risultato = fd.arbitri("SA", date(2025, 7, 1), date(2026, 6, 30))
    assert rotta.call_count == 1
    richiesta = rotta.calls[0].request
    assert dict(richiesta.url.params) == {"season": "2025"}
    assert richiesta.headers["X-Auth-Token"] == "chiave-segreta"
    assert len(risultato) == 6


@respx.mock
def test_intervallo_diviso_in_blocchi_da_dieci_giorni(fd):
    rotta = respx.get(URL_SA).mock(return_value=httpx.Response(200, json={"matches": []}))
    fd.arbitri("SA", date(2025, 10, 1), date(2025, 10, 25))
    parametri = [dict(c.request.url.params) for c in rotta.calls]
    assert parametri == [
        {"dateFrom": "2025-10-01", "dateTo": "2025-10-10"},
        {"dateFrom": "2025-10-11", "dateTo": "2025-10-20"},
        {"dateFrom": "2025-10-21", "dateTo": "2025-10-25"},
    ]


@respx.mock
def test_un_giorno_una_richiesta(fd):
    rotta = respx.get(URL_SA).mock(return_value=httpx.Response(200, json={"matches": []}))
    fd.arbitri("SA", date(2025, 10, 1), date(2025, 10, 1))
    assert [dict(c.request.url.params) for c in rotta.calls] == [
        {"dateFrom": "2025-10-01", "dateTo": "2025-10-01"}
    ]


# --- lettura -----------------------------------------------------------------


@respx.mock
def test_lettura_partite_e_arbitri(fd):
    respx.get(URL_SA).mock(return_value=httpx.Response(200, json=corpo()))
    risultato = fd.arbitri("SA", date(2025, 7, 1), date(2026, 6, 30))
    assert risultato[0] == ArbitroPartita(
        data_utc=datetime(2025, 8, 23, 16, 30, tzinfo=timezone.utc),
        casa="Genoa CFC",
        trasferta="US Lecce",
        arbitro_id=11029,
        arbitro_nome="Davide Massa",
    )
    # due voci "REFEREE" nella stessa partita: la prima
    assert risultato[4].arbitro_nome == "Luca Zufferli"
    # nessun arbitro ancora designato: la partita c'è, senza arbitro
    assert risultato[5].arbitro_id is None and risultato[5].arbitro_nome is None
    assert risultato[5].casa == "Venezia FC"


@respx.mock
def test_solo_arbitro_principale(fd):
    dati = {"matches": [{
        "utcDate": "2025-08-23T16:30:00Z",
        "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
        "referees": [
            {"id": 1, "name": "Var Uno", "type": "VIDEO_ASSISTANT_REFEREE_N1"},
            {"id": 2, "name": "Arbitro Due", "type": "REFEREE"},
        ],
    }]}
    respx.get(URL_SA).mock(return_value=httpx.Response(200, json=dati))
    [p] = fd.arbitri("SA", date(2025, 8, 23), date(2025, 8, 23))
    assert (p.arbitro_id, p.arbitro_nome) == (2, "Arbitro Due")


@respx.mock
def test_partita_malformata_saltata_con_log(fd, caplog):
    dati = {"matches": [
        {"utcDate": "non-una-data", "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"}},
        {"utcDate": "2025-08-23T16:30:00Z", "homeTeam": {"name": None}, "awayTeam": {"name": "B"}},
        corpo()["matches"][0],
    ]}
    respx.get(URL_SA).mock(return_value=httpx.Response(200, json=dati))
    risultato = fd.arbitri("SA", date(2025, 8, 23), date(2025, 8, 23))
    assert [p.casa for p in risultato] == ["Genoa CFC"]
    assert "non letta" in caplog.text


@respx.mock
def test_risposta_senza_matches_errore_chiaro(fd):
    respx.get(URL_SA).mock(return_value=httpx.Response(200, json={"x": 1}))
    with pytest.raises(ErroreFonte, match="matches"):
        fd.arbitri("SA", date(2025, 8, 23), date(2025, 8, 23))


# --- errori e retry ----------------------------------------------------------


@respx.mock
def test_chiave_rifiutata_errore_senza_retry_e_senza_chiave_nel_messaggio(fd, attese):
    rotta = respx.get(URL_SA).mock(return_value=httpx.Response(403, json={"message": "no"}))
    with pytest.raises(ErroreFonte) as e:
        fd.arbitri("SA", date(2025, 8, 23), date(2025, 8, 23))
    assert rotta.call_count == 1
    assert attese == []
    assert "403" in str(e.value) and "chiave-segreta" not in str(e.value)


@respx.mock
def test_retry_su_429_e_500_poi_riuscita(fd, attese):
    rotta = respx.get(URL_SA).mock(side_effect=[
        httpx.Response(429), httpx.Response(500), httpx.Response(200, json=corpo()),
    ])
    assert len(fd.arbitri("SA", date(2025, 7, 1), date(2026, 6, 30))) == 6
    assert rotta.call_count == 3
    assert attese == [1, 2]


@respx.mock
def test_tentativi_esauriti(fd, attese):
    respx.get(URL_SA).mock(return_value=httpx.Response(503))
    with pytest.raises(ErroreFonte, match="5 tentativi"):
        fd.arbitri("SA", date(2025, 8, 23), date(2025, 8, 23))
    assert attese == [1, 2, 4, 8]


@respx.mock
def test_errore_di_rete_ritentato(fd, attese):
    rotta = respx.get(URL_SA).mock(side_effect=[
        httpx.ConnectError("giù"), httpx.Response(200, json={"matches": []}),
    ])
    assert fd.arbitri("SA", date(2025, 8, 23), date(2025, 8, 23)) == []
    assert rotta.call_count == 2


@respx.mock
def test_limite_prende_una_richiesta_per_chiamata_http():
    limite = LimiteRichiesteLocale(max_giorno=2, max_minuto=10, dormi=lambda s: None)
    rotta = respx.get(URL_SA).mock(return_value=httpx.Response(200, json={"matches": []}))
    with httpx.Client() as client:
        fonte = FootballData("k", limite, client=client)
        with pytest.raises(LimiteSuperato):
            fonte.arbitri("SA", date(2025, 10, 1), date(2025, 10, 25))  # 3 blocchi
    # il terzo blocco supera il tetto di 2: prima della richiesta HTTP
    assert rotta.call_count == 2


@respx.mock
def test_limite_giornaliero_superato_solleva():
    limite = LimiteRichiesteLocale(max_giorno=1, dormi=lambda s: None)
    respx.get(URL_SA).mock(return_value=httpx.Response(200, json={"matches": []}))
    with httpx.Client() as client:
        fonte = FootballData("k", limite, client=client)
        fonte.arbitri("SA", date(2025, 10, 1), date(2025, 10, 1))
        with pytest.raises(LimiteSuperato):
            fonte.arbitri("SA", date(2025, 10, 2), date(2025, 10, 2))


# --- limite locale -----------------------------------------------------------


def test_crea_limite_football_data_valori():
    l = crea_limite_football_data()
    assert isinstance(l, LimiteRichiesteLocale) and isinstance(l, LimiteRichieste)
    assert (l.max_minuto, l.max_giorno, l.riserva_oggi) == (10, 1000, 0)
    assert l.rimanenti(Priorita.OGGI) == 1000


def test_limite_locale_non_tocca_il_database_ne_il_contatore_condiviso(sessione):
    from ammonizioni.db.modelli import ContatoreRichieste
    from sqlalchemy import select

    l = LimiteRichiesteLocale(dormi=lambda s: None)
    for _ in range(5):
        l.prendi(Priorita.OGGI)
    assert l.rimanenti(Priorita.OGGI) == 995
    assert sessione.scalars(select(ContatoreRichieste)).all() == []


def test_limite_locale_ritmo_e_azzeramento_giornaliero():
    attese = []
    t = [1000.0]
    giorno = [date(2026, 11, 5)]

    def dormi(s):
        attese.append(s)
        t[0] += s

    l = LimiteRichiesteLocale(
        max_giorno=12, orologio=lambda: t[0], dormi=dormi, oggi=lambda: giorno[0]
    )
    for _ in range(11):
        l.prendi(Priorita.OGGI)
    assert attese == [pytest.approx(60)]  # l'undicesima aspetta il minuto
    giorno[0] = date(2026, 11, 6)
    assert l.rimanenti(Priorita.OGGI) == 12


# --- chiave ------------------------------------------------------------------


def test_chiave_football_data_da_ambiente_poi_da_database(sessione, monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_KEY", raising=False)
    assert config.chiave_football_data() is None
    assert config.chiave_football_data(sessione) is None
    repo.scrivi_impostazione(sessione, "chiave_football_data", "dal-db")
    assert config.chiave_football_data(sessione) == "dal-db"
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "da-env")
    assert config.chiave_football_data(sessione) == "da-env"
