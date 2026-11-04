import pytest
from costruttori import riga

from ammonizioni.motore.fattori.situazione import fattore_situazione
from ammonizioni.motore.pesi import Pesi


def _storico_4_gialli_serie_a_2026():
    return [riga(gialli=1) for _ in range(4)]


def test_diffidato_abbassa():
    f = fattore_situazione(_storico_4_gialli_serie_a_2026(), 2026, Pesi())
    assert f.nome == "situazione"
    assert f.valore == pytest.approx(0.85)
    assert f.motivazione == "Diffidato"
    assert f.n_dati == 4


def test_gialli_in_coppa_non_contano_per_diffida():
    storico = [riga(gialli=1, competizione_id=137) for _ in range(4)]
    f = fattore_situazione(storico, 2026, Pesi())
    assert f.valore == 1.0
    assert f.motivazione is None
    assert f.n_dati == 0


def test_gialli_di_altra_stagione_non_contano():
    storico = [riga(gialli=1, stagione=2025) for _ in range(4)]
    f = fattore_situazione(storico, 2026, Pesi())
    assert f.valore == 1.0


def test_spesso_sostituito_presto():
    storico = [riga(minuti=50) for _ in range(5)]
    f = fattore_situazione(storico, 2026, Pesi())
    assert f.valore == pytest.approx(0.90)
    assert f.motivazione == "Spesso sostituito presto"


def test_usa_solo_le_ultime_5_da_titolare():
    vecchie = [riga(minuti=30) for _ in range(5)]
    recenti = [riga(minuti=90) for _ in range(5)]
    f = fattore_situazione(vecchie + recenti, 2026, Pesi())
    assert f.valore == 1.0


def test_riserve_ignorate_per_sostituzione():
    storico = [riga(minuti=10, titolare=False) for _ in range(5)]
    f = fattore_situazione(storico, 2026, Pesi())
    assert f.valore == 1.0
    assert f.motivazione is None


def test_nessun_titolare_nessun_effetto_sostituzione():
    f = fattore_situazione([], 2026, Pesi())
    assert (f.valore, f.motivazione, f.n_dati) == (1.0, None, 0)


def test_diffidato_e_sostituito_si_combinano():
    storico = [riga(gialli=1, minuti=50) for _ in range(4)]
    f = fattore_situazione(storico, 2026, Pesi())
    assert f.valore == pytest.approx(0.85 * 0.90)
    assert f.motivazione == "Diffidato · Spesso sostituito presto"


def test_valore_limitato():
    pesi = Pesi(limiti_fattore=(0.95, 1.6))
    f = fattore_situazione(_storico_4_gialli_serie_a_2026(), 2026, pesi)
    assert f.valore == pytest.approx(0.95)
