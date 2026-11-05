from datetime import date, datetime, timezone

import pytest

from ammonizioni.db.modelli import Giocata, Giocatore, Partita, Presenza, Squadra
from ammonizioni.giocate.registro import aggiorna_esiti, aggiungi_giocata, statistiche_per_fonte

GIORNO = date(2026, 10, 3)


def crea_partita(s, id=1, stato="FT", scaricate=True):
    for sid, nome in ((1, "Juventus"), (2, "Inter")):
        if s.get(Squadra, sid) is None:
            s.add(Squadra(id=sid, nome=nome))
    s.add(
        Partita(
            id=id,
            data_utc=datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc),
            competizione_id=135,
            stagione=2026,
            casa_id=1,
            trasferta_id=2,
            stato=stato,
            statistiche_scaricate=scaricate,
        )
    )
    s.flush()


def crea_giocatore_con_presenza(s, giocatore_id, partita_id=1, minuti=90, gialli=0, rossi=0):
    s.add(Giocatore(id=giocatore_id, nome=f"G{giocatore_id}"))
    s.flush()
    if minuti is not None:
        s.add(
            Presenza(
                partita_id=partita_id,
                giocatore_id=giocatore_id,
                squadra_id=1,
                minuti=minuti,
                gialli=gialli,
                rossi=rossi,
            )
        )
    s.flush()


def test_aggiungi_giocata_parte_in_attesa(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10)
    g = aggiungi_giocata(sessione, 1, 10, "Tipster", 2.5, 10.0, GIORNO)
    assert g.id is not None
    assert (g.esito, g.fonte, g.quota, g.puntata, g.data) == ("in_attesa", "Tipster", 2.5, 10.0, GIORNO)


@pytest.mark.parametrize("quota,puntata", [(1.0, 10.0), (0.5, 10.0), (2.0, 0.0), (2.0, -5.0)])
def test_aggiungi_giocata_valida_quota_e_puntata(sessione, quota, puntata):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10)
    with pytest.raises(ValueError):
        aggiungi_giocata(sessione, 1, 10, "Tipster", quota, puntata, GIORNO)


def test_giallo_vinta(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, gialli=1)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 1
    assert sessione.query(Giocata).one().esito == "vinta"


@pytest.mark.parametrize("stato", ["AET", "PEN"])
def test_partita_finita_ai_supplementari_o_ai_rigori_decisa(sessione, stato):
    crea_partita(sessione, stato=stato)
    crea_giocatore_con_presenza(sessione, 10, gialli=1)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 1
    assert sessione.query(Giocata).one().esito == "vinta"


def test_senza_giallo_persa_anche_con_rosso_diretto(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, gialli=0)
    crea_giocatore_con_presenza(sessione, 11, gialli=0, rossi=1)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    aggiungi_giocata(sessione, 1, 11, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 2
    assert {g.esito for g in sessione.query(Giocata)} == {"persa"}


def test_non_entrato_rimborsata(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, minuti=0)
    crea_giocatore_con_presenza(sessione, 11, minuti=None)  # nessuna presenza
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    aggiungi_giocata(sessione, 1, 11, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 2
    assert {g.esito for g in sessione.query(Giocata)} == {"rimborsata"}


def test_partita_cancellata_rimborsata(sessione):
    crea_partita(sessione, stato="CANC", scaricate=False)
    crea_giocatore_con_presenza(sessione, 10, minuti=None)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 1
    assert sessione.query(Giocata).one().esito == "rimborsata"


def test_partita_non_giocata_resta_in_attesa(sessione):
    crea_partita(sessione, id=1, stato="NS", scaricate=False)
    crea_partita(sessione, id=2, stato="FT", scaricate=False)  # finita ma senza statistiche
    crea_giocatore_con_presenza(sessione, 10, partita_id=1, minuti=None)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    aggiungi_giocata(sessione, 2, 10, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 0
    assert {g.esito for g in sessione.query(Giocata)} == {"in_attesa"}


def test_aggiorna_esiti_non_tocca_giocate_gia_chiuse(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, gialli=1)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 1
    assert aggiorna_esiti(sessione) == 0


def test_profitto_e_rendimento(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, gialli=1)
    crea_giocatore_con_presenza(sessione, 11, gialli=0)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    aggiungi_giocata(sessione, 1, 11, "A", 2.0, 10.0, GIORNO)
    aggiorna_esiti(sessione)
    [stat] = statistiche_per_fonte(sessione)
    assert (stat.fonte, stat.giocate, stat.vinte, stat.perse) == ("A", 2, 1, 1)
    assert stat.percentuale_successo == pytest.approx(0.5)
    assert stat.profitto == pytest.approx(10.0)
    assert stat.rendimento == pytest.approx(0.5)
    assert stat.prob_implicita_media == pytest.approx((1 / 3 + 1 / 2) / 2)
    assert stat.prob_implicita_media == pytest.approx(0.4167, abs=1e-4)


def test_rimborsate_escluse_dalle_statistiche(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, gialli=1)
    crea_giocatore_con_presenza(sessione, 11, minuti=0)
    crea_giocatore_con_presenza(sessione, 12, gialli=0)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    aggiungi_giocata(sessione, 1, 11, "A", 5.0, 10.0, GIORNO)  # rimborsata
    aggiungi_giocata(sessione, 1, 11, "Solo rimborsi", 5.0, 10.0, GIORNO)  # fonte omessa
    aggiungi_giocata(sessione, 1, 12, "A", 2.0, 10.0, GIORNO)
    aggiorna_esiti(sessione)
    stats = statistiche_per_fonte(sessione)
    assert [s.fonte for s in stats] == ["A"]
    assert stats[0].giocate == 2
    assert stats[0].profitto == pytest.approx(10.0)


def test_in_attesa_escluse_e_fonti_ordinate_per_nome(sessione):
    crea_partita(sessione, id=1)
    crea_partita(sessione, id=2, stato="NS", scaricate=False)
    crea_giocatore_con_presenza(sessione, 10, gialli=1)
    aggiungi_giocata(sessione, 1, 10, "Zeta", 2.0, 10.0, GIORNO)
    aggiungi_giocata(sessione, 1, 10, "Alfa", 2.0, 10.0, GIORNO)
    aggiungi_giocata(sessione, 2, 10, "Alfa", 2.0, 10.0, GIORNO)  # in attesa
    aggiorna_esiti(sessione)
    stats = statistiche_per_fonte(sessione)
    assert [s.fonte for s in stats] == ["Alfa", "Zeta"]
    assert stats[0].giocate == 1


def test_nessuna_giocata_nessuna_statistica(sessione):
    assert statistiche_per_fonte(sessione) == []


def test_ammonito_dalla_panchina_senza_entrare_vinta(sessione):
    """Il cartellino e' stato mostrato anche se il giocatore non e' mai entrato (0 minuti)."""
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, minuti=0, gialli=1)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    assert aggiorna_esiti(sessione) == 1
    assert sessione.query(Giocata).one().esito == "vinta"


def test_subentrato_per_un_minuto_e_ammonito_vinta(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, minuti=1, gialli=1)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    aggiorna_esiti(sessione)
    assert sessione.query(Giocata).one().esito == "vinta"


def test_subentrato_per_un_minuto_senza_giallo_persa(sessione):
    crea_partita(sessione)
    crea_giocatore_con_presenza(sessione, 10, minuti=1, gialli=0)
    aggiungi_giocata(sessione, 1, 10, "A", 3.0, 10.0, GIORNO)
    aggiorna_esiti(sessione)
    assert sessione.query(Giocata).one().esito == "persa"
