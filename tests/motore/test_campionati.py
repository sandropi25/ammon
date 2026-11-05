"""Più campionati (Serie A e Liga) nello stesso database: ogni partita usa i dati del proprio
campionato, e la Serie A non cambia quando si aggiunge la Liga."""
from datetime import datetime, timedelta, timezone

import pytest
from costruttori import riga
from db_prova import PARTITA_FUTURA, popola

from ammonizioni.db.modelli import (
    Arbitro,
    Formazione,
    Giocatore,
    ListaManuale,
    Partita,
    Presenza,
    Squadra,
)
from ammonizioni.motore.dati import MEDIE_PREDEFINITE, carica_dati
from ammonizioni.motore.fattori.situazione import fattore_situazione
from ammonizioni.motore.mercati import MercatoAmmonizioni
from ammonizioni.motore.pesi import Pesi

SERIE_A, COPPA_ITALIA, LIGA, COPA_DEL_REY, CHAMPIONS = 135, 137, 140, 143, 2
LIGA_CASA, LIGA_TRASF = 501, 502
INIZIO = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
GIORNO = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def _liga_squadre_e_giocatori(s):
    """Due squadre di Liga con un giocatore per ruolo (id 5xx / 6xx), un arbitro di Liga."""
    s.add_all([Squadra(id=LIGA_CASA, nome="Liga Casa"), Squadra(id=LIGA_TRASF, nome="Liga Trasf")])
    s.add(Arbitro(id=50, nome_normalizzato="gil manzano", nome_visualizzato="Gil Manzano"))
    giocatori = {
        LIGA_CASA: [(511, "G", "1:1"), (512, "D", "2:1"), (513, "M", "3:1"), (514, "F", "4:1")],
        LIGA_TRASF: [(521, "G", "1:1"), (522, "D", "2:1"), (523, "M", "3:1"), (524, "F", "4:1")],
    }
    for lista in giocatori.values():
        for gid, ruolo, _ in lista:
            s.add(Giocatore(id=gid, nome=f"Liga {gid}", ruolo=ruolo))
    s.flush()
    return giocatori


def _liga_partita(s, pid, quando, giocatori, *, gialli=2, falli=4, dribbling=0, voto=None,
                  futura=False, competizione=LIGA, vittoria_casa=True):
    """Partita di Liga (giocata con presenze, oppure futura con formazione ufficiale)."""
    s.add(Partita(
        id=pid, data_utc=quando, competizione_id=competizione, stagione=2026, giornata=pid,
        casa_id=LIGA_CASA, trasferta_id=LIGA_TRASF, arbitro_id=50,
        gol_casa=None if futura else (1 if vittoria_casa else 0),
        gol_trasferta=None if futura else 0,
        stato="NS" if futura else "FT",
        stato_formazioni="ufficiali", statistiche_scaricate=not futura,
    ))
    s.flush()
    for sq, lista in giocatori.items():
        for gid, ruolo, griglia in lista:
            if futura:
                s.add(Formazione(partita_id=pid, squadra_id=sq, giocatore_id=gid,
                                 tipo="ufficiale", griglia=griglia))
            else:
                s.add(Presenza(
                    partita_id=pid, giocatore_id=gid, squadra_id=sq, titolare=True, ruolo=ruolo,
                    griglia=griglia, minuti=90, gialli=gialli if ruolo != "G" else 0,
                    falli_commessi=falli, falli_subiti=2, dribbling_tentati=dribbling, voto=voto,
                ))
    s.flush()


def test_partita_di_liga_e_serie_a_nello_stesso_giorno_hanno_medie_separate(sessione):
    popola(sessione)  # Serie A: 6 partite, 4 gialli e 16 falli per partita
    giocatori = _liga_squadre_e_giocatori(sessione)
    for i in range(6):  # Liga: 6 gialli e 24 falli per partita (3 non portieri x 2 squadre)
        _liga_partita(sessione, 600 + i, INIZIO + timedelta(days=7 * i + 1), giocatori)
    _liga_partita(sessione, 700, GIORNO, giocatori, futura=True)  # stesso giorno di Serie A

    serie_a = carica_dati(sessione, PARTITA_FUTURA)
    liga = carica_dati(sessione, 700)

    assert serie_a.campionato_id == SERIE_A and liga.campionato_id == LIGA
    assert serie_a.medie.gialli_partita == pytest.approx(2.0)
    assert serie_a.medie.falli_partita == pytest.approx(16.0)
    assert liga.medie.gialli_partita == pytest.approx(12.0)
    assert liga.medie.falli_partita == pytest.approx(32.0)
    assert liga.medie.per_ruolo["D"].falli90 == pytest.approx(4.0)
    assert serie_a.medie.per_ruolo["D"].falli90 == pytest.approx(2.0)


def test_lega_senza_dribbling_calcolata_per_campionato(sessione):
    """Serie A con dribbling e Liga senza (o viceversa): il dato assente vale solo per la
    lega della partita, non si propaga all'altra."""
    popola(sessione)
    sessione.query(Presenza).update({Presenza.dribbling_tentati: 3, Presenza.voto: 6.0})
    giocatori = _liga_squadre_e_giocatori(sessione)
    for i in range(6):
        _liga_partita(sessione, 600 + i, INIZIO + timedelta(days=7 * i + 1), giocatori,
                      dribbling=0, voto=None)
    _liga_partita(sessione, 700, GIORNO, giocatori, futura=True)

    serie_a = carica_dati(sessione, PARTITA_FUTURA).medie
    liga = carica_dati(sessione, 700).medie
    assert serie_a.per_ruolo["D"].dribbling90 == pytest.approx(3.0)
    assert serie_a.per_ruolo["D"].voto == pytest.approx(6.0)
    assert all(m.dribbling90 == 0.0 and m.voto is None for m in liga.per_ruolo.values())


def test_posta_e_classifica_separate_per_campionato(sessione):
    popola(sessione)
    giocatori = _liga_squadre_e_giocatori(sessione)
    # Serie A: la squadra di casa vince 19 volte (+ 6 pareggi iniziali) -> titolo
    for i in range(19):
        sessione.add(Partita(
            id=200 + i, data_utc=INIZIO + timedelta(days=43, hours=i), competizione_id=SERIE_A,
            stagione=2026, casa_id=1, trasferta_id=2, gol_casa=1, gol_trasferta=0, stato="FT"))
    # Liga: 25 vittorie (75 punti): se le classifiche fossero unite, la Serie A (63 punti con i
    # 6 pareggi iniziali) non sarebbe piu' a 3 punti dalla prima
    for i in range(25):
        sessione.add(Partita(
            id=300 + i, data_utc=INIZIO + timedelta(days=43, hours=i), competizione_id=LIGA,
            stagione=2026, casa_id=LIGA_CASA, trasferta_id=LIGA_TRASF, gol_casa=1, gol_trasferta=0,
            stato="FT"))
    sessione.flush()
    _liga_partita(sessione, 700, GIORNO, giocatori, futura=True)

    assert carica_dati(sessione, PARTITA_FUTURA).contesto.posta == {1: "titolo", 2: None}
    assert carica_dati(sessione, 700).contesto.posta == {LIGA_CASA: "titolo", LIGA_TRASF: None}


def test_posta_di_liga_non_vede_la_serie_a(sessione):
    """Solo 18 partite di Liga e 19 di Serie A: la Liga non arriva alle 19 giocate."""
    popola(sessione)
    giocatori = _liga_squadre_e_giocatori(sessione)
    for i in range(18):
        sessione.add(Partita(
            id=300 + i, data_utc=INIZIO + timedelta(days=43, hours=i), competizione_id=LIGA,
            stagione=2026, casa_id=LIGA_CASA, trasferta_id=LIGA_TRASF, gol_casa=1, gol_trasferta=0,
            stato="FT"))
    for i in range(19):
        sessione.add(Partita(
            id=200 + i, data_utc=INIZIO + timedelta(days=43, hours=i), competizione_id=SERIE_A,
            stagione=2026, casa_id=LIGA_CASA + 100, trasferta_id=LIGA_TRASF + 100, gol_casa=1,
            gol_trasferta=0, stato="FT"))
    sessione.add_all([Squadra(id=LIGA_CASA + 100, nome="X"), Squadra(id=LIGA_TRASF + 100, nome="Y")])
    sessione.flush()
    _liga_partita(sessione, 700, GIORNO, giocatori, futura=True)
    assert carica_dati(sessione, 700).contesto.posta == {LIGA_CASA: None, LIGA_TRASF: None}


@pytest.mark.parametrize(
    "competizione,squadre,atteso",
    [
        (COPPA_ITALIA, (1, 2), SERIE_A),
        (COPA_DEL_REY, (LIGA_CASA, LIGA_TRASF), LIGA),
        (CHAMPIONS, (LIGA_CASA, LIGA_TRASF), LIGA),  # solo squadre di Liga
        (CHAMPIONS, (1, LIGA_TRASF), SERIE_A),  # c'e' una squadra di Serie A: precedenza
        (CHAMPIONS, (LIGA_CASA, 1), SERIE_A),
        (CHAMPIONS, (901, 902), SERIE_A),  # squadre sconosciute: Serie A, come prima
    ],
)
def test_campionato_di_coppe(sessione, competizione, squadre, atteso):
    popola(sessione)
    giocatori = _liga_squadre_e_giocatori(sessione)
    for i in range(3):
        _liga_partita(sessione, 600 + i, INIZIO + timedelta(days=i + 1), giocatori)
    sessione.add_all([Squadra(id=901, nome="Z1"), Squadra(id=902, nome="Z2")])
    sessione.flush()
    sessione.add(Partita(
        id=800, data_utc=GIORNO, competizione_id=competizione, stagione=2026,
        casa_id=squadre[0], trasferta_id=squadre[1], stato="NS"))
    sessione.flush()
    assert carica_dati(sessione, 800).campionato_id == atteso


def test_diffida_di_liga_gialli_in_liga_non_in_copa_del_rey():
    storico = [riga(gialli=1, competizione_id=LIGA) for _ in range(4)]
    storico += [riga(gialli=1, competizione_id=COPA_DEL_REY) for _ in range(3)]
    f = fattore_situazione(storico, 2026, Pesi(), LIGA)
    assert f.valore == pytest.approx(0.85)
    assert f.motivazione == "Diffidato"
    assert f.n_dati == 4  # solo le presenze del campionato


def test_diffida_di_liga_non_conta_i_gialli_di_serie_a_ne_della_coppa():
    # 4 gialli in Copa del Rey e 3 in Liga (7 in tutto): nessuna soglia
    storico = [riga(gialli=1, competizione_id=COPA_DEL_REY) for _ in range(4)]
    storico += [riga(gialli=1, competizione_id=LIGA) for _ in range(3)]
    assert fattore_situazione(storico, 2026, Pesi(), LIGA).valore == 1.0
    # 4 gialli in Serie A non fanno diffidare in una partita di Liga
    solo_serie_a = [riga(gialli=1, competizione_id=SERIE_A) for _ in range(4)]
    assert fattore_situazione(solo_serie_a, 2026, Pesi(), LIGA).valore == 1.0


def test_soglie_di_diffida_per_campionato():
    # 14 gialli: soglia della Liga (4, 9, 14, 19) ma non della Serie A (4, 9, 13, 16, 19)
    in_liga = [riga(gialli=1, competizione_id=LIGA) for _ in range(14)]
    in_serie_a = [riga(gialli=1, competizione_id=SERIE_A) for _ in range(14)]
    assert fattore_situazione(in_liga, 2026, Pesi(), LIGA).motivazione == "Diffidato"
    assert fattore_situazione(in_serie_a, 2026, Pesi(), SERIE_A).motivazione is None
    # 13 gialli: soglia della Serie A ma non della Liga
    tredici_liga = [riga(gialli=1, competizione_id=LIGA) for _ in range(13)]
    tredici_serie_a = [riga(gialli=1, competizione_id=SERIE_A) for _ in range(13)]
    assert fattore_situazione(tredici_serie_a, 2026, Pesi(), SERIE_A).motivazione == "Diffidato"
    assert fattore_situazione(tredici_liga, 2026, Pesi(), LIGA).motivazione is None


def test_serie_a_usa_ancora_le_soglie_dei_pesi_modificati():
    """Per la Serie A contano le soglie dei pesi (modificabili da Impostazioni), come prima."""
    storico = [riga(gialli=1) for _ in range(5)]
    assert fattore_situazione(storico, 2026, Pesi()).motivazione is None
    assert fattore_situazione(storico, 2026, Pesi(soglie_diffida=(5,))).motivazione == "Diffidato"


def test_giocatore_diffidato_in_liga_nel_motore(sessione):
    """4 gialli in Liga + 3 in Copa del Rey: nella partita di Liga il fattore situazione scende."""
    popola(sessione)
    giocatori = _liga_squadre_e_giocatori(sessione)
    quando = INIZIO
    for i in range(4):  # 4 gialli del difensore 512 in Liga
        _liga_partita(sessione, 600 + i, quando + timedelta(days=i + 1), giocatori, gialli=0)
        sessione.get(Presenza, (600 + i, 512)).gialli = 1
    for i in range(3):  # e 3 in Copa del Rey
        _liga_partita(sessione, 650 + i, quando + timedelta(days=10 + i), giocatori, gialli=0,
                      competizione=COPA_DEL_REY)
        sessione.get(Presenza, (650 + i, 512)).gialli = 1
    _liga_partita(sessione, 700, GIORNO, giocatori, futura=True)
    sessione.flush()
    candidati = MercatoAmmonizioni().classifica(sessione, 700)
    c = next(x for x in candidati if x.giocatore_id == 512)
    situazione = next(f for f in c.fattori if f.nome == "situazione")
    assert situazione.valore == pytest.approx(0.85) and situazione.motivazione == "Diffidato"
    altro = next(x for x in candidati if x.giocatore_id == 522)
    assert next(f for f in altro.fattori if f.nome == "situazione").valore == 1.0


def test_aggiungere_la_liga_non_cambia_la_classifica_di_serie_a(sessione):
    """Guardia di regressione: stessa partita di Serie A, stessa classifica (probabilita',
    motivazioni, fattori) prima e dopo aver aggiunto partite, giocatori, arbitri e liste della Liga."""
    popola(sessione)
    sessione.add(ListaManuale(tipo="campo_caldo", squadra_a_id=1))
    sessione.flush()
    prima = MercatoAmmonizioni().classifica(sessione, PARTITA_FUTURA, quote={12: 3.0})
    prima_dati = carica_dati(sessione, PARTITA_FUTURA)
    assert prima and any(c.motivazioni for c in prima)

    giocatori = _liga_squadre_e_giocatori(sessione)
    for i in range(8):  # stesse date delle partite di Serie A, e anche dopo: molto rumore
        _liga_partita(sessione, 600 + i, INIZIO + timedelta(days=7 * i, hours=1), giocatori,
                      gialli=3, falli=9, dribbling=4, voto=7.5)
    for i in range(3):
        _liga_partita(sessione, 650 + i, INIZIO + timedelta(days=i + 1), giocatori, gialli=1,
                      competizione=COPA_DEL_REY)
    for i in range(25):  # classifica di Liga con tanti punti
        sessione.add(Partita(
            id=300 + i, data_utc=INIZIO + timedelta(days=43, hours=i), competizione_id=LIGA,
            stagione=2026, casa_id=LIGA_CASA, trasferta_id=LIGA_TRASF, gol_casa=3, gol_trasferta=0,
            stato="FT"))
    _liga_partita(sessione, 700, GIORNO, giocatori, futura=True)  # stesso giorno e ora
    sessione.add(ListaManuale(tipo="derby", squadra_a_id=LIGA_CASA, squadra_b_id=LIGA_TRASF))
    sessione.add(ListaManuale(tipo="campo_caldo", squadra_a_id=LIGA_CASA))
    sessione.flush()

    dopo = MercatoAmmonizioni().classifica(sessione, PARTITA_FUTURA, quote={12: 3.0})
    dopo_dati = carica_dati(sessione, PARTITA_FUTURA)
    assert dopo == prima  # Candidato e Fattore sono dataclass: confronto completo
    assert [c.motivazioni for c in dopo] == [c.motivazioni for c in prima]
    assert dopo_dati.medie == prima_dati.medie
    assert dopo_dati.contesto == prima_dati.contesto
    assert dopo_dati.arbitro == prima_dati.arbitro
    assert dopo_dati.campionato_id == SERIE_A
    # e la prova che la Liga e' davvero nel database con dati propri
    assert carica_dati(sessione, 700).medie != prima_dati.medie


def test_senza_dati_di_liga_medie_predefinite(sessione):
    """Una partita di Liga senza storico di Liga non prende le medie della Serie A."""
    popola(sessione)
    giocatori = _liga_squadre_e_giocatori(sessione)
    _liga_partita(sessione, 700, GIORNO, giocatori, futura=True)
    assert carica_dati(sessione, 700).medie == MEDIE_PREDEFINITE
