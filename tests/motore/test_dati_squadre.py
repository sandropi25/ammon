from datetime import timedelta
from decimal import Decimal

import pytest
from db_prova import CASA, INIZIO, PARTITA_FUTURA, TRASF, popola

from ammonizioni.db.modelli import Partita, Presenza
from ammonizioni.motore.dati import _stat_squadre, carica_dati
from ammonizioni.motore.tipi import StatSquadra


def test_gialli_fatti_e_provocati_delle_squadre(sessione):
    popola(sessione)
    # un giallo dalla panchina (0 minuti) conta
    p = sessione.get(Presenza, (1, 13))
    p.minuti, p.titolare, p.gialli = 0, False, 1
    sessione.flush()
    d = carica_dati(sessione, PARTITA_FUTURA)
    # partite pari: 2 gialli per squadra; partita 1: il giallo dalla panchina del 13
    assert d.stat_squadre[CASA] == StatSquadra(6.0, 7.0, 6.0)
    assert d.stat_squadre[TRASF] == StatSquadra(6.0, 6.0, 7.0)


def test_stagione_precedente_a_meta_peso_e_niente_futuro(sessione):
    popola(sessione)
    sessione.get(Partita, 1).stagione = 2025
    sessione.flush()
    # prima della partita 4: partite 1 (2025, metà peso), 2 e 3
    d = carica_dati(sessione, PARTITA_FUTURA, prima_di=INIZIO + timedelta(days=7 * 4))
    assert d.stat_squadre[CASA] == StatSquadra(2.5, 2.0, 2.0)


def test_somme_decimal_diventano_numeri():
    class Risultato:
        def __init__(self, righe):
            self.righe = righe

        def all(self):
            return self.righe

    class S:
        risposte = [
            Risultato([(1, CASA, TRASF, 2026)]),
            Risultato([(1, CASA, Decimal("3")), (1, TRASF, Decimal("1"))]),
        ]

        def execute(self, _):
            return self.risposte.pop(0)

    class P:
        id, casa_id, trasferta_id, stagione = 99, CASA, TRASF, 2026

    stat = _stat_squadre(S(), P(), INIZIO, 135)
    assert stat[CASA] == StatSquadra(1.0, 3.0, 1.0)
    assert type(stat[CASA].gialli_fatti) is float
    assert stat[TRASF].gialli_provocati == pytest.approx(3.0)
