import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from ammonizioni.caricamento import arbitri_fd
from ammonizioni.caricamento.arbitri_fd import (
    collega,
    nome_squadra_normalizzato,
    stessa_squadra,
)
from ammonizioni.db.modelli import Arbitro, Partita, Squadra
from ammonizioni.fonti.football_data import (
    URL_FOOTBALL_DATA,
    ArbitroPartita,
    FootballData,
)

DATI = Path(__file__).parent.parent / "dati_prova" / "football_data"

# Nomi reali (ESPN, football-data.org) di TUTTE le squadre dei campionati, ricavati il
# 2026-11-05 da una chiamata per stagione a ESPN (scoreboard) e a football-data.org
# (/competitions/{codice}/matches?season=...) e abbinati per data e ora delle partite.
SERIE_A = {
    2024: [
        ("AC Milan", "AC Milan"), ("Monza", "AC Monza"), ("Fiorentina", "ACF Fiorentina"),
        ("AS Roma", "AS Roma"), ("Atalanta", "Atalanta BC"), ("Bologna", "Bologna FC 1909"),
        ("Cagliari", "Cagliari Calcio"), ("Como", "Como 1907"), ("Empoli", "Empoli FC"),
        ("Internazionale", "FC Internazionale Milano"), ("Genoa", "Genoa CFC"),
        ("Hellas Verona", "Hellas Verona FC"), ("Juventus", "Juventus FC"),
        ("Parma", "Parma Calcio 1913"), ("Lazio", "SS Lazio"), ("Napoli", "SSC Napoli"),
        ("Torino", "Torino FC"), ("Lecce", "US Lecce"), ("Udinese", "Udinese Calcio"),
        ("Venezia", "Venezia FC"),
    ],
    2025: [
        ("AC Milan", "AC Milan"), ("Pisa", "AC Pisa 1909"), ("Fiorentina", "ACF Fiorentina"),
        ("AS Roma", "AS Roma"), ("Atalanta", "Atalanta BC"), ("Bologna", "Bologna FC 1909"),
        ("Cagliari", "Cagliari Calcio"), ("Como", "Como 1907"),
        ("Internazionale", "FC Internazionale Milano"), ("Genoa", "Genoa CFC"),
        ("Hellas Verona", "Hellas Verona FC"), ("Juventus", "Juventus FC"),
        ("Parma", "Parma Calcio 1913"), ("Lazio", "SS Lazio"), ("Napoli", "SSC Napoli"),
        ("Torino", "Torino FC"), ("Cremonese", "US Cremonese"), ("Lecce", "US Lecce"),
        ("Sassuolo", "US Sassuolo Calcio"), ("Udinese", "Udinese Calcio"),
    ],
    2026: [
        ("AC Milan", "AC Milan"), ("Monza", "AC Monza"), ("Fiorentina", "ACF Fiorentina"),
        ("AS Roma", "AS Roma"), ("Atalanta", "Atalanta BC"), ("Bologna", "Bologna FC 1909"),
        ("Cagliari", "Cagliari Calcio"), ("Como", "Como 1907"),
        ("Internazionale", "FC Internazionale Milano"), ("Frosinone", "Frosinone Calcio"),
        ("Genoa", "Genoa CFC"), ("Juventus", "Juventus FC"), ("Parma", "Parma Calcio 1913"),
        ("Lazio", "SS Lazio"), ("Napoli", "SSC Napoli"), ("Torino", "Torino FC"),
        ("Lecce", "US Lecce"), ("Sassuolo", "US Sassuolo Calcio"), ("Udinese", "Udinese Calcio"),
        ("Venezia", "Venezia FC"),
    ],
}
LIGA = {
    2026: [
        ("Athletic Club", "Athletic Club"), ("Osasuna", "CA Osasuna"),
        ("Atlético Madrid", "Club Atlético de Madrid"), ("Alavés", "Deportivo Alavés"),
        ("Elche", "Elche CF"), ("Barcelona", "FC Barcelona"), ("Getafe", "Getafe CF"),
        ("Levante", "Levante UD"), ("Málaga", "Málaga CF"), ("Celta Vigo", "RC Celta de Vigo"),
        ("Deportivo", "RC Deportivo La Coruña"), ("Espanyol", "RCD Espanyol de Barcelona"),
        ("Rayo Vallecano", "Rayo Vallecano de Madrid"), ("Real Betis", "Real Betis Balompié"),
        ("Real Madrid", "Real Madrid CF"), ("Racing Santander", "Real Racing Club de Santander"),
        ("Real Sociedad", "Real Sociedad de Fútbol"), ("Sevilla", "Sevilla FC"),
        ("Valencia", "Valencia CF"), ("Villarreal", "Villarreal CF"),
    ],
}
TUTTE_LE_COPPIE = [
    pytest.param(espn, fd, id=f"{campionato}-{stagione}-{espn}")
    for campionato, stagioni in (("SA", SERIE_A), ("PD", LIGA))
    for stagione, coppie in stagioni.items()
    for espn, fd in coppie
]


# --- nomi delle squadre ------------------------------------------------------


@pytest.mark.parametrize("espn,fd", TUTTE_LE_COPPIE)
def test_coppie_reali_di_nomi_corrispondono(espn, fd):
    assert stessa_squadra(espn, fd)


@pytest.mark.parametrize(
    "campionato,stagione,coppie",
    [("SA", s, c) for s, c in SERIE_A.items()] + [("PD", s, c) for s, c in LIGA.items()],
)
def test_nessuna_confusione_tra_squadre_della_stessa_stagione(campionato, stagione, coppie):
    """Ogni squadra ESPN corrisponde a una sola squadra football-data e viceversa."""
    assert len(coppie) in (19, 20)
    for espn, fd in coppie:
        uguali_a_fd = [f for _, f in coppie if stessa_squadra(espn, f)]
        uguali_a_espn = [e for e, _ in coppie if stessa_squadra(e, fd)]
        assert uguali_a_fd == [fd]
        assert uguali_a_espn == [espn]


def test_squadre_diverse_non_corrispondono():
    assert not stessa_squadra("Internazionale", "AC Milan")
    assert not stessa_squadra("Real Madrid", "Atlético Madrid")
    assert not stessa_squadra("Real Madrid", "Club Atlético de Madrid")
    assert not stessa_squadra("Atlético Madrid", "Real Madrid CF")
    assert not stessa_squadra("Genoa", "Venezia FC")


@pytest.mark.parametrize(
    "a,b",
    [
        ("Internazionale", "Inter"),
        ("AS Roma", "Roma"),
        ("Atlético Madrid", "Club Atlético de Madrid"),
        ("Hellas Verona", "Verona"),
        ("Juventus", "JUVENTUS FC"),
    ],
)
def test_alias_e_normalizzazione(a, b):
    assert stessa_squadra(a, b)


def test_normalizzazione_toglie_accenti_sigle_e_anno():
    assert nome_squadra_normalizzato("Bologna FC 1909") == "bologna"
    assert nome_squadra_normalizzato("SSC Napoli") == "napoli"
    assert nome_squadra_normalizzato("Málaga CF") == "malaga"
    assert nome_squadra_normalizzato("Udinese Calcio") == "udinese"
    assert nome_squadra_normalizzato("Deportivo Alavés") == nome_squadra_normalizzato("Alavés")


def test_alias_senza_catene():
    assert arbitri_fd.ALIAS_SQUADRE
    for chiave, valore in arbitri_fd.ALIAS_SQUADRE.items():
        assert valore not in arbitri_fd.ALIAS_SQUADRE
        assert chiave != valore


# --- collega -----------------------------------------------------------------


class FonteFdFinta:
    def __init__(self, voci, chiave="chiave-finta"):
        self.chiave = chiave
        self.voci = voci
        self.chiamate = []

    def arbitri(self, codice, dal, al):
        self.chiamate.append((codice, dal, al))
        return list(self.voci)


def voce(data, casa, trasferta, arbitro=("Davide Massa", 11029)):
    nome, id_ = arbitro if arbitro else (None, None)
    return ArbitroPartita(data, casa, trasferta, id_, nome)


def aggiungi_partita(
    s, id, data, casa, trasferta, competizione_id=135, stagione=2025, arbitro_id=None
):
    for sid, nome in casa, trasferta:
        if s.get(Squadra, sid) is None:
            s.add(Squadra(id=sid, nome=nome))
    s.flush()
    p = Partita(
        id=id, data_utc=data, competizione_id=competizione_id, stagione=stagione,
        casa_id=casa[0], trasferta_id=trasferta[0], arbitro_id=arbitro_id, stato="NS",
    )
    s.add(p)
    s.flush()
    return p


GENOA = (107, "Genoa")
LECCE = (113, "Lecce")
INTER = (110, "Internazionale")
MILAN = (103, "AC Milan")
T0 = datetime(2025, 8, 23, 16, 30, tzinfo=timezone.utc)
GIORNO = date(2025, 8, 23)


def nome_arbitro(s, partita_id):
    p = s.get(Partita, partita_id)
    return None if p.arbitro_id is None else s.get(Arbitro, p.arbitro_id).nome_visualizzato


def test_collegamento_riuscito(sessione):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce")])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 1
    assert nome_arbitro(sessione, 1) == "Davide Massa"
    assert fd.chiamate == [("SA", GIORNO, GIORNO)]


def test_orario_spostato_di_due_ore(sessione):
    aggiungi_partita(sessione, 1, T0 + timedelta(hours=2), GENOA, LECCE)
    aggiungi_partita(sessione, 2, T0 - timedelta(hours=2), MILAN, INTER)
    fd = FonteFdFinta([
        voce(T0, "Genoa CFC", "US Lecce"),
        voce(T0, "AC Milan", "FC Internazionale Milano", ("Luca Zufferli", 1)),
    ])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 2
    assert nome_arbitro(sessione, 1) == "Davide Massa"
    assert nome_arbitro(sessione, 2) == "Luca Zufferli"


def test_orario_spostato_di_oltre_tre_ore_non_collega(sessione, caplog):
    aggiungi_partita(sessione, 1, T0 + timedelta(hours=3, minutes=1), GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce")])
    with caplog.at_level(logging.WARNING):
        assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0
    assert nome_arbitro(sessione, 1) is None


def test_tre_ore_esatte_collega(sessione):
    aggiungi_partita(sessione, 1, T0 + timedelta(hours=3), GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce")])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 1


def test_alias_internazionale(sessione):
    aggiungi_partita(sessione, 1, T0, INTER, MILAN)
    fd = FonteFdFinta([voce(T0, "FC Internazionale Milano", "AC Milan")])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 1


def test_nessuna_corrispondenza_arbitro_none_e_log(sessione, caplog):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "Torino FC", "Udinese Calcio")])
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.arbitri_fd"):
        assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0
    assert nome_arbitro(sessione, 1) is None
    assert sessione.scalars(select(Arbitro)).all() == []
    assert "Genoa" in caplog.text and "Lecce" in caplog.text


def test_una_sola_squadra_uguale_non_basta(sessione):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([
        voce(T0, "Genoa CFC", "Torino FC"),
        voce(T0, "Torino FC", "US Lecce"),
    ])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0
    assert nome_arbitro(sessione, 1) is None


def test_casa_e_trasferta_invertite_non_collegano(sessione):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "US Lecce", "Genoa CFC")])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0


def test_stesse_squadre_il_giorno_dopo_non_collega(sessione):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([voce(T0 + timedelta(days=1), "Genoa CFC", "US Lecce")])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0


def test_piu_candidati_vince_il_calcio_d_inizio_piu_vicino(sessione):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([
        voce(T0 - timedelta(hours=2), "Genoa CFC", "US Lecce", ("Luca Zufferli", 1)),
        voce(T0 + timedelta(minutes=30), "Genoa CFC", "US Lecce", ("Davide Massa", 2)),
        voce(T0 + timedelta(hours=2), "Genoa CFC", "US Lecce", ("Giuseppe Collu", 3)),
    ])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 1
    assert nome_arbitro(sessione, 1) == "Davide Massa"


def test_arbitro_non_ancora_designato_non_collega(sessione, caplog):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce", arbitro=None)])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0
    assert nome_arbitro(sessione, 1) is None
    assert sessione.scalars(select(Arbitro)).all() == []


def test_stesso_arbitro_in_due_competizioni_una_riga(sessione):
    """Serie A e un'altra competizione (qui la Liga: l'unica altra con codice
    football-data in config; la Champions arriva con arbitro da `salva_partita`)."""
    altra = datetime(2025, 9, 16, 19, 0, tzinfo=timezone.utc)
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    aggiungi_partita(
        sessione, 2, altra, (1, "Real Madrid"), (2, "Barcelona"), competizione_id=140
    )
    serie_a = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce", ("Davide Massa", 11029))])
    coppa = FonteFdFinta([
        voce(altra, "Real Madrid CF", "FC Barcelona", ("Davide MASSA, Italy", 99))
    ])
    assert collega(sessione, serie_a, 135, GIORNO, GIORNO) == 1
    assert collega(sessione, coppa, 140, date(2025, 9, 16), date(2025, 9, 16)) == 1
    arbitri = sessione.scalars(select(Arbitro)).all()
    assert len(arbitri) == 1
    assert sessione.get(Partita, 1).arbitro_id == sessione.get(Partita, 2).arbitro_id


def test_arbitro_di_champions_da_salva_partita_e_da_football_data_una_riga(sessione):
    """Stessa persona da due fonti (nome API-Football e nome football-data): una riga."""
    from ammonizioni.caricamento.arbitri import trova_o_crea

    a = trova_o_crea(sessione, "Daniele Doveri, Italy")
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce", ("Daniele Doveri", 7))])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 1
    assert sessione.get(Partita, 1).arbitro_id == a.id
    assert len(sessione.scalars(select(Arbitro)).all()) == 1


def test_partite_con_arbitro_gia_assegnato_restano(sessione):
    esistente = Arbitro(nome_normalizzato="doveri", nome_visualizzato="Daniele Doveri")
    sessione.add(esistente)
    sessione.flush()
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE, arbitro_id=esistente.id)
    fd = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce")])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0
    assert nome_arbitro(sessione, 1) == "Daniele Doveri"


def test_nessuna_partita_senza_arbitro_nessuna_chiamata(sessione):
    fd = FonteFdFinta([])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0
    assert fd.chiamate == []


def test_solo_la_competizione_e_le_date_richieste(sessione):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    aggiungi_partita(sessione, 2, T0 + timedelta(days=10), MILAN, INTER)
    aggiungi_partita(
        sessione, 3, T0, (1, "Real Madrid"), (2, "Barcelona"), competizione_id=140
    )
    fd = FonteFdFinta([
        voce(T0, "Genoa CFC", "US Lecce"),
        voce(T0 + timedelta(days=10), "AC Milan", "FC Internazionale Milano"),
        voce(T0, "Real Madrid CF", "FC Barcelona"),
    ])
    assert collega(sessione, fd, 135, GIORNO, GIORNO) == 1
    assert nome_arbitro(sessione, 2) is None
    assert nome_arbitro(sessione, 3) is None


def test_competizione_senza_codice_football_data(sessione, caplog):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE, competizione_id=137)
    fd = FonteFdFinta([])
    with caplog.at_level(logging.WARNING):
        assert collega(sessione, fd, 137, GIORNO, GIORNO) == 0
    assert fd.chiamate == []


@pytest.mark.parametrize("chiave", [None, ""])
def test_senza_chiave_non_fa_nulla_e_logga(sessione, caplog, chiave):
    aggiungi_partita(sessione, 1, T0, GENOA, LECCE)
    fd = FonteFdFinta([voce(T0, "Genoa CFC", "US Lecce")], chiave=chiave)
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.arbitri_fd"):
        assert collega(sessione, fd, 135, GIORNO, GIORNO) == 0
    assert fd.chiamate == []
    assert nome_arbitro(sessione, 1) is None
    assert "FOOTBALL_DATA_KEY" in caplog.text


def test_integrazione_con_risposta_reale_ridotta(sessione):
    """Risposta reale di football-data.org (ridotta) letta da FootballData e collegata."""
    corpo = json.loads((DATI / "matches_ridotto.json").read_text(encoding="utf-8"))
    aggiungi_partita(sessione, 1, datetime(2025, 8, 23, 16, 30, tzinfo=timezone.utc),
                     (107, "Genoa"), (113, "Lecce"))
    aggiungi_partita(sessione, 2, datetime(2025, 8, 23, 16, 30, tzinfo=timezone.utc),
                     (3997, "Sassuolo"), (114, "Napoli"))
    aggiungi_partita(sessione, 3, datetime(2025, 8, 23, 18, 45, tzinfo=timezone.utc),
                     (103, "AC Milan"), (4050, "Cremonese"))
    aggiungi_partita(sessione, 4, datetime(2025, 8, 23, 18, 45, tzinfo=timezone.utc),
                     (104, "AS Roma"), (105, "Bologna"))
    with respx.mock:
        rotta = respx.get(f"{URL_FOOTBALL_DATA}/competitions/SA/matches").mock(
            return_value=httpx.Response(200, json=corpo)
        )
        with httpx.Client() as client:
            fonte = FootballData("chiave-di-prova", client=client)
            n = collega(sessione, fonte, 135, date(2025, 8, 23), date(2025, 8, 23))
    assert rotta.call_count == 1
    assert n == 4
    assert [nome_arbitro(sessione, i) for i in (1, 2, 3, 4)] == [
        "Davide Massa", "Giovanni Ayroldi", "Giuseppe Collu", "Luca Zufferli",
    ]
