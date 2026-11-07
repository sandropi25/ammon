"""Stima e prova di V2: niente dati del futuro, ogni cartellino conta."""
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from ammonizioni.backtest import v2 as bv2
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Arbitro, Giocatore, Partita, Presenza
from ammonizioni.motore import modello, v2
from ammonizioni.motore.pesi import Pesi

from test_prova import INIZIO, ROSE, STAGIONE, aggiungi_partita, anagrafica

PANCHINA = {1: (15, "M"), 2: (25, "D")}


def _campionato(s, partite=8):
    anagrafica(s)
    s.add_all([Giocatore(id=gid, nome=f"Riserva {gid}", ruolo=r) for gid, r in PANCHINA.values()])
    s.add(Arbitro(id=1, nome_normalizzato="rossi", nome_visualizzato="Rossi"))
    s.flush()
    for i in range(1, partite + 1):
        aggiungi_partita(s, i, 7 * i, gialli={12: i % 2, 23: 1 if i % 3 == 0 else 0, 24: 1})
        s.get(Partita, i).arbitro_id = 1
        for sq, (gid, _) in PANCHINA.items():
            # in panchina: il 25 prende un giallo senza entrare nella partita 4
            s.add(Presenza(partita_id=i, giocatore_id=gid, squadra_id=sq, titolare=False,
                           minuti=15 if i % 2 else 0, gialli=1 if (gid == 25 and i == 4) else 0))
    s.flush()


def test_caratteristiche_non_vedono_il_futuro(sessione):
    _campionato(sessione)
    partita = sessione.get(Partita, 5)
    prima = bv2.estrai_partita(sessione, partita, Pesi())

    # il futuro cambia (partite 6-8, e i gialli della partita 5 stessa): niente deve muoversi
    for p in sessione.query(Presenza).filter(Presenza.partita_id >= 5):
        p.gialli, p.falli_commessi, p.minuti = 2, 9, 90
    sessione.add(Partita(
        id=50, data_utc=INIZIO + timedelta(days=36), competizione_id=135, stagione=STAGIONE,
        casa_id=1, trasferta_id=2, arbitro_id=1, stato="FT", statistiche_scaricate=True,
        gol_casa=0, gol_trasferta=3,
    ))
    sessione.flush()
    for gid, ruolo in ROSE[1] + ROSE[2]:
        sessione.add(Presenza(partita_id=50, giocatore_id=gid, squadra_id=1 if gid < 20 else 2,
                              titolare=True, ruolo=ruolo, minuti=90, gialli=1))
    sessione.flush()
    dopo = bv2.estrai_partita(sessione, partita, Pesi())

    assert np.array_equal(prima.x, dopo.x) and prima.offset == dopo.offset
    assert np.array_equal(prima.Z, dopo.Z)
    assert np.array_equal(prima.log_minuti, dopo.log_minuti)
    assert prima.p_v1 == dopo.p_v1 and prima.candidati_v1 == dopo.candidati_v1
    assert prima.semplice == dopo.semplice
    # cambia solo l'esito della partita stessa
    assert dopo.gialli_totali != prima.gialli_totali


def test_ogni_cartellino_conta_anche_dalla_panchina(sessione):
    _campionato(sessione)
    riga = bv2.estrai_partita(sessione, sessione.get(Partita, 4), Pesi())
    gialli = dict(zip(riga.ids.tolist(), riga.gialli.tolist()))
    assert gialli[25] == 1  # ammonito in panchina, 0 minuti
    assert riga.gialli_totali == 2  # il 24 in campo e il 25 in panchina


def test_stima_e_valuta(sessione):
    _campionato(sessione, partite=12)
    partite = bv2.estrai(sessione, STAGIONE, 135)
    assert len(partite) == 12
    coeff = bv2.stima(partite)
    assert coeff.campione["partite"] == 12 and coeff.campione["stagioni"] == [STAGIONE]
    assert coeff.campione["gialli"] == sum(p.gialli_totali for p in partite)
    assert set(coeff.partita) == set(v2.NOMI_PARTITA)
    assert set(coeff.giocatore) == set(v2.NOMI_GIOCATORE)
    assert set(coeff.calibrazione) == {"a", "b"}
    assert bv2.stima(partite, platt=False).calibrazione == {}
    # il 24 prende sempre giallo: con i pesi stimati è il più probabile
    lam, prob = bv2.probabilita_v2(partite[-1], coeff)
    assert max(prob, key=prob.get) == 24
    val = bv2.valuta(partite, coeff)
    assert val.v2.partite == val.v1.partite == val.semplice.partite == 12
    assert val.v2.successi == 12
    assert 0 <= val.v2.brier <= 1 and val.v2.log_loss > 0
    assert len(val.v2.decili) == 10
    assert val.v2_grezzo.successi == val.v2.successi  # Platt non cambia la classifica
    testo = bv2.testo_valutazione(val, "Prova")
    assert "V2 senza Platt" in testo and "Scelta semplice" in testo
    assert "Platt" in bv2.testo_coefficienti(coeff)
    assert val.lambda_somme.reali_medi == pytest.approx(
        np.mean([p.gialli_totali for p in partite])
    )


def _script(nome):
    cartella = Path(__file__).resolve().parents[2] / "scripts"
    if str(cartella) not in sys.path:
        sys.path.insert(0, str(cartella))  # prova_v2 importa calibra_v2
    spec = importlib.util.spec_from_file_location(f"{nome}_script", cartella / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _db_con_due_stagioni(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'prova.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    with modulo_sessione.apri(url) as s:
        _campionato(s, partite=6)
        # stessa rosa una stagione prima
        for i in range(1, 7):
            aggiungi_partita(s, 100 + i, -400 + 7 * i, gialli={24: 1, 13: i % 2})
            s.get(Partita, 100 + i).stagione = STAGIONE - 1
        s.flush()
    return url


def test_script_calibra_salva_i_coefficienti(tmp_path, monkeypatch, capsys):
    url = _db_con_due_stagioni(tmp_path, monkeypatch)
    codice = _script("calibra_v2").main(
        ["--stagioni", str(STAGIONE), "--campionati", "135", "--salva"]
    )
    fuori = capsys.readouterr().out
    assert codice == 0
    assert "Livello partita" in fuori and "Platt" in fuori and "Coefficienti salvati" in fuori
    with modulo_sessione.apri(url) as s:
        coeff = modello.carica_coefficienti(s)
        assert coeff.campione["partite"] == 6 and coeff.campione["stagioni"] == [STAGIONE]
        assert modello.modello_scelto(s) == "V1"  # salvare i pesi non cambia il modello


def test_script_prova_fuori_campione(tmp_path, monkeypatch, capsys):
    _db_con_due_stagioni(tmp_path, monkeypatch)
    codice = _script("prova_v2").main(
        ["--addestra", str(STAGIONE - 1), "--prova", str(STAGIONE), "--campionati", "135"]
    )
    fuori = capsys.readouterr().out
    assert codice == 0
    assert f"Serie A {STAGIONE} (V2 stimato su {STAGIONE - 1})" in fuori
    for metodo in ("| V1 |", "| V2 |", "| V2 senza Platt |", "| Scelta semplice |"):
        assert metodo in fuori
    assert _script("prova_v2").main(["--addestra", "2025", "--prova", "2025"]) == 2


def test_cache_rilegge_senza_ricalcolare(sessione, tmp_path):
    _campionato(sessione, partite=3)
    prima = bv2.estrai_con_cache(sessione, STAGIONE, 135, tmp_path)
    assert (tmp_path / f"v2_135_{STAGIONE}.pkl").exists()
    sessione.query(Presenza).delete()
    sessione.flush()
    dopo = bv2.estrai_con_cache(sessione, STAGIONE, 135, tmp_path)
    assert [p.partita_id for p in dopo] == [p.partita_id for p in prima]
