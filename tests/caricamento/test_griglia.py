"""Griglia (posizione in campo) dalla formazione ufficiale alle presenze, alle probabili
e al fattore duello. /fixtures/players non la fornisce: senza formazione ufficiale resta None."""
from datetime import datetime, timedelta, timezone

from conftest import FonteFinta, partita_dati

from ammonizioni.caricamento import formazioni, notturno
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza
from ammonizioni.motore.mercati import MercatoAmmonizioni
from ammonizioni.scheduler import pre_partita

ADESSO = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
FUTURA = 200
INIZIO_FUTURA = ADESSO + timedelta(days=3)


def ufficiale(s, partita_id, squadra_id, giocatore_id, griglia):
    if s.get(Giocatore, giocatore_id) is None:
        s.add(Giocatore(id=giocatore_id, nome=f"G{giocatore_id}"))
        s.flush()
    s.add(
        Formazione(
            partita_id=partita_id, squadra_id=squadra_id, giocatore_id=giocatore_id,
            tipo="ufficiale", griglia=griglia,
        )
    )
    s.flush()


def flusso_fino_alla_classifica(s):
    """Notte (statistiche della partita 1), probabili della partita futura dall'ultimo XI,
    poi la classifica: restituisce i candidati."""
    notturno.esegui(s, FonteFinta(partite_ft=1, due_squadre=True), adesso=ADESSO)
    notturno.salva_partita(
        s, partita_dati(FUTURA, INIZIO_FUTURA, casa=(11, "Casa 1"), stato="NS", giornata=2)
    )
    s.commit()
    pre_partita.esegui(s, FonteFinta(), INIZIO_FUTURA - timedelta(minutes=30))
    return MercatoAmmonizioni().classifica(s, FUTURA)


def test_presenza_senza_formazione_ufficiale_resta_senza_griglia(sessione):
    notturno.esegui(sessione, FonteFinta(partite_ft=1), adesso=ADESSO)
    assert sessione.get(Presenza, (1, 101)).griglia is None


def test_presenza_prende_la_griglia_dalla_formazione_ufficiale(sessione):
    notturno.aggiorna_calendario(sessione, FonteFinta(partite_ft=1))
    ufficiale(sessione, 1, 11, 101, "2:3")
    sessione.commit()
    notturno.esegui(sessione, FonteFinta(partite_ft=1), adesso=ADESSO)
    assert sessione.get(Presenza, (1, 101)).griglia == "2:3"


def test_griglia_esistente_non_sovrascritta_con_none(sessione):
    notturno.esegui(sessione, FonteFinta(partite_ft=1), adesso=ADESSO)
    sessione.get(Presenza, (1, 101)).griglia = "4:1"
    sessione.get(Partita, 1).statistiche_scaricate = False
    sessione.commit()
    notturno.esegui(sessione, FonteFinta(partite_ft=1), adesso=ADESSO)  # riscarica
    assert sessione.get(Partita, 1).statistiche_scaricate is True
    assert sessione.get(Presenza, (1, 101)).griglia == "4:1"


def test_flusso_senza_griglia_nessun_crash_e_duello_neutro(sessione):
    candidati = flusso_fino_alla_classifica(sessione)
    probabili = sessione.query(Formazione).filter_by(partita_id=FUTURA, tipo="probabile").all()
    assert sorted(f.giocatore_id for f in probabili) == [101, 102]
    assert all(f.griglia is None for f in probabili)
    assert {c.giocatore_id for c in candidati} == {101, 102}
    for c in candidati:
        assert c.avversario_diretto_id is None
        duello = next(f for f in c.fattori if f.nome == "duello")
        assert duello.valore == 1.0


def test_flusso_con_formazione_ufficiale_trova_l_avversario_diretto(sessione):
    notturno.aggiorna_calendario(sessione, FonteFinta(partite_ft=1))
    ufficiale(sessione, 1, 11, 101, "2:1")
    ufficiale(sessione, 1, 2, 102, "4:1")
    sessione.commit()
    candidati = flusso_fino_alla_classifica(sessione)
    probabili = {
        f.giocatore_id: f.griglia
        for f in sessione.query(Formazione).filter_by(partita_id=FUTURA, tipo="probabile")
    }
    assert probabili == {101: "2:1", 102: "4:1"}
    difensore = next(c for c in candidati if c.giocatore_id == 101)
    assert difensore.avversario_diretto_id == 102


def test_ultimo_xi_usa_la_griglia_della_formazione_ufficiale_se_manca_nella_presenza(sessione):
    notturno.esegui(sessione, FonteFinta(partite_ft=1), adesso=ADESSO)  # griglia None
    ufficiale(sessione, 1, 11, 101, "2:2")  # ufficiale salvata, presenza gia' scaricata
    xi = formazioni.ultimo_xi(sessione, 11, INIZIO_FUTURA)
    assert [(t.giocatore_id, t.griglia) for t in xi] == [(101, "2:2")]


def test_salva_probabili_con_griglie(sessione):
    notturno.esegui(sessione, FonteFinta(partite_ft=1, due_squadre=True), adesso=ADESSO)
    formazioni.salva_probabili(sessione, 1, {11: [101], 2: [102]}, griglie={101: "2:1"})
    righe = {
        f.giocatore_id: f.griglia
        for f in sessione.query(Formazione).filter_by(partita_id=1, tipo="probabile")
    }
    assert righe == {101: "2:1", 102: None}
