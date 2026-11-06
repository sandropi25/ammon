"""Panchina nei dati della partita e regressione: i titolari di Serie A non cambiano."""
from dataclasses import replace
from decimal import Decimal

import pytest
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola, popola_panchina

from ammonizioni.db.modelli import Partita
from ammonizioni.motore import dati as modulo_dati
from ammonizioni.motore.classifica import classifica, classifica_subentranti
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.pesi import Pesi

# Probabilità e ordine dei titolari calcolati con il codice di main (prima dei subentranti,
# commit 7b1521f) sugli stessi dati: devono restare identici, con e senza panchina.
TITOLARI_PRIMA = [
    (14, 0.5098691563155414), (22, 0.5049730333454052), (24, 0.4978071228683706),
    (12, 0.49613814805120443), (13, 0.04346330463909896), (23, 0.04346330463909896),
]


@pytest.mark.parametrize("salvata", [True, False], ids=["ufficiali", "probabili"])
@pytest.mark.parametrize("con_panchina", [False, True])
def test_regressione_titolari_identici_a_prima(sessione, salvata, con_panchina):
    popola(sessione, con_formazione=salvata)
    popola_panchina(sessione, salvata=salvata)
    dati = carica_dati(sessione, PARTITA_FUTURA, con_panchina=con_panchina)
    c = classifica(dati, Pesi())
    assert [(x.giocatore_id, x.probabilita) for x in c] == TITOLARI_PRIMA
    assert not any(x.subentrante for x in c)


def test_senza_richiesta_nessuna_panchina(sessione):
    popola(sessione)
    popola_panchina(sessione)
    dati = carica_dati(sessione, PARTITA_FUTURA)
    assert dati.panchina == [] and dati.tendenza_cambi == {} and dati.prob_vittoria == {}
    assert 15 not in dati.storico


def test_panchina_salvata_con_le_ufficiali(sessione):
    popola(sessione)
    popola_panchina(sessione)
    dati = carica_dati(sessione, PARTITA_FUTURA, con_panchina=True)
    assert sorted((b.giocatore_id, b.squadra_id) for b in dati.panchina) == [
        (15, CASA), (16, CASA), (17, CASA), (25, TRASF)]
    assert dati.prob_vittoria == {CASA: 0.55, TRASF: 0.20}
    assert dati.tendenza_cambi[CASA] == {"F": 1.0}
    assert len(dati.storico[15]) == 6


def test_subentranti_della_partita(sessione):
    popola(sessione)
    popola_panchina(sessione)
    dati = carica_dati(sessione, PARTITA_FUTURA, con_panchina=True)
    sub = {c.giocatore_id: c for c in classifica_subentranti(dati, Pesi())}
    # terzo portiere e difensore che non entra mai: fuori; punta di riserva al posto della
    # punta titolare (esce al 70')
    assert set(sub) == {15, 25}
    assert sub[15].subentro.al_posto_di_id == 14
    assert sub[25].subentro.al_posto_di_id is None  # il mediano titolare non esce mai
    assert sub[25].subentro.sfavorita and not sub[15].subentro.sfavorita
    # il giallo preso dalla panchina (0 minuti) conta nel suo tasso
    senza_giallo = replace(dati, storico={
        **dati.storico, 25: [replace(r, gialli=0) for r in dati.storico[25]]})
    altro = next(c for c in classifica_subentranti(senza_giallo, Pesi()) if c.giocatore_id == 25)
    assert sub[25].fattori[0].valore > altro.fattori[0].valore


def test_panchina_automatica_con_le_probabili(sessione):
    """Formazioni probabili (nessuna panchina salvata): entrati in almeno 2 delle ultime 5."""
    popola(sessione, con_formazione=False)
    popola_panchina(sessione, salvata=False)
    dati = carica_dati(sessione, PARTITA_FUTURA, con_panchina=True)
    ids = sorted(b.giocatore_id for b in dati.panchina)
    # 15 entra in 2,3,4,6 delle ultime 5 (2..6); 25 in 2,4,5; i titolari restano fuori
    assert ids == [15, 25]


def test_squadra_senza_panchina_nota_nessun_errore(sessione):
    popola(sessione, con_formazione=False)  # nessun panchinaro nei dati
    dati = carica_dati(sessione, PARTITA_FUTURA, con_panchina=True)
    assert dati.panchina == []
    assert classifica_subentranti(dati, Pesi()) == []


def test_panchina_data_dalla_prova_storica(sessione):
    popola(sessione)
    popola_panchina(sessione)
    titolari = carica_dati(sessione, PARTITA_FUTURA).titolari
    data = [b for b in carica_dati(sessione, PARTITA_FUTURA, con_panchina=True).panchina
            if b.giocatore_id == 25]
    dati = carica_dati(sessione, PARTITA_FUTURA, titolari=titolari, panchina=data)
    assert [b.giocatore_id for b in dati.panchina] == [25]


def test_quote_decimal_convertite(sessione):
    """Su Postgres le colonne numeriche possono arrivare come Decimal: sempre float."""
    popola(sessione)
    popola_panchina(sessione)
    p = sessione.get(Partita, PARTITA_FUTURA)
    p.prob_casa, p.prob_trasferta = Decimal("0.55"), Decimal("0.20")
    dati = carica_dati(sessione, PARTITA_FUTURA, con_panchina=True)
    assert all(type(v) is float for v in dati.prob_vittoria.values())


def test_punti_partita_interi_anche_da_decimal():
    giocate = [(1, 2, Decimal(2), Decimal(0))] * 3 + [(2, 1, Decimal(1), Decimal(1))]
    punti = modulo_dati._punti_partita(giocate, (1, 2))
    assert punti == {1: pytest.approx(10 / 4), 2: pytest.approx(1 / 4)}
    assert all(type(v) is float for v in punti.values())
    assert modulo_dati._punti_partita(giocate[:2], (1, 2)) == {}
