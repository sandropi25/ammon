from datetime import datetime, timedelta, timezone

import numpy as np

from ammonizioni.marcatori import verifica
from ammonizioni.marcatori.modello import (
    Giocante,
    Parametri,
    PartitaM,
    PresenzaM,
    Storico,
)

INIZIO = datetime(2025, 8, 20, 18, 0, tzinfo=timezone.utc)


def partita(i, casa=1, trasf=2, gc=1, gt=1, giorni=0):
    return PartitaM(i, INIZIO + timedelta(days=giorni), 135, 2025, casa, trasf, gc, gt)


def storico_con_bomber():
    s = Storico(Parametri())
    for i in range(10):
        gc = 2
        s.aggiorna(partita(i, gc=gc, gt=0, giorni=7 * i), [
            PresenzaM(10, 1, True, "F", 90, 2, 5),  # bomber: 2 gol a partita
            PresenzaM(11, 1, True, "D", 90, 0, 0),
            PresenzaM(12, 1, True, "G", 90, 0, 0),
            PresenzaM(20, 2, True, "F", 90, 0, 1),
        ])
    return s


def test_bomber_in_cima_portiere_in_fondo():
    s = storico_con_bomber()
    rosa = [Giocante(12, 1, True), Giocante(11, 1, True), Giocante(10, 1, True)]
    prev = s.prevedi(partita(99, giorni=80), rosa)
    assert [p.giocatore_id for p in prev] == [10, 11, 12]
    assert prev[0].probabilita > 0.4
    assert prev[-1].probabilita < 0.02
    assert prev[0].ruolo == "F" and prev[-1].ruolo == "G"  # ruolo preso dallo storico


def test_giocatore_nuovo_ha_la_probabilita_del_suo_ruolo():
    s = storico_con_bomber()
    prev = s.prevedi(partita(99, giorni=80), [Giocante(77, 1, True, "F"), Giocante(78, 1, True, "D")])
    att, dif = {p.giocatore_id: p.probabilita for p in prev}[77], {p.giocatore_id: p.probabilita for p in prev}[78]
    assert 0.05 < att < 0.6 and 0 < dif < att


def test_in_casa_e_contro_una_difesa_debole_si_segna_di_piu():
    s = storico_con_bomber()  # la squadra 2 ha subito 2 gol a partita
    gioc = [Giocante(10, 1, True)]
    contro_debole = s.prevedi(partita(99, casa=1, trasf=2, giorni=80), gioc)[0].probabilita
    contro_nuova = s.prevedi(partita(99, casa=1, trasf=3, giorni=80), gioc)[0].probabilita
    in_trasferta = s.prevedi(partita(99, casa=3, trasf=1, giorni=80), gioc)[0].probabilita
    assert contro_debole > contro_nuova > in_trasferta


def test_dalla_panchina_meno_che_da_titolare():
    s = storico_con_bomber()
    tit = s.prevedi(partita(99, giorni=80), [Giocante(10, 1, True)])[0].probabilita
    pan = s.prevedi(partita(99, giorni=80), [Giocante(10, 1, False)])[0].probabilita
    assert pan < tit / 2


def test_rientro_e_fatica():
    s = storico_con_bomber()
    f_rientro = s.fattori(partita(99, giorni=63 + 30), [Giocante(10, 1, True)])[0]
    f_subito = s.fattori(partita(99, giorni=63 + 3), [Giocante(10, 1, True)])[0]
    assert f_rientro.rientro == 1 and f_subito.rientro == 0
    assert f_subito.fatica == 1.0 and f_rientro.fatica == 0


def test_derby():
    s = storico_con_bomber()
    s.derby = {frozenset((1, 2))}
    assert s.fattori(partita(99, giorni=80), [Giocante(10, 1, True)])[0].derby == 1
    assert s.fattori(partita(99, casa=1, trasf=3, giorni=80), [Giocante(10, 1, True)])[0].derby == 0


def test_percorri_non_usa_la_partita_stessa():
    partite = [partita(i, gc=1, gt=0, giorni=7 * i) for i in range(6)]
    presenze = {i: [PresenzaM(10, 1, True, "F", 90, 0, 0)] for i in range(6)}
    presenze[5] = [PresenzaM(10, 1, True, "F", 90, 3, 6)]  # tripletta solo nell'ultima
    righe = verifica.percorri(partite, presenze, Parametri())
    assert [r.partita_id for r in righe] == [3, 4, 5]
    assert righe[-1].segnato
    assert righe[-1].x[0] <= righe[-2].x[0] + 1e-9  # niente gol visti: il ritmo non sale


def test_logistica_ritrova_i_pesi():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(20000, 2))
    y = (rng.random(20000) < 1 / (1 + np.exp(-(-1 + 0.8 * x[:, 0] - 0.5 * x[:, 1])))).astype(float)
    beta = verifica.logistica(x, y, l2=0.0)
    assert np.allclose(beta, [-1, 0.8, -0.5], atol=0.08)


def test_parametri_json_ignora_chiavi_extra():
    p = Parametri(a=0.3, c_derby=-0.1)
    assert Parametri.da_json(p.a_json() | {"stimati_utc": "x"}) == p
    assert Parametri.da_json(None) == Parametri()
