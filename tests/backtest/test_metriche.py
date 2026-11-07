import math

import pytest

from ammonizioni.backtest import metriche as m


def test_brier_e_log_loss():
    assert m.brier([0.2, 0.9], [0, 1]) == pytest.approx((0.04 + 0.01) / 2)
    atteso = -(math.log(0.8) + math.log(0.9)) / 2
    assert m.log_loss([0.2, 0.9], [0, 1]) == pytest.approx(atteso)
    # probabilità 0 su un evento accaduto: limitata, non infinita
    assert math.isfinite(m.log_loss([0.0], [1]))


def test_decili_dividono_per_numero_e_confrontano():
    p = [i / 100 for i in range(100)]
    y = [1 if i >= 90 else 0 for i in range(100)]
    d = m.decili(p, y)
    assert len(d) == 10 and all(x.n == 10 for x in d)
    assert d[0].previsto == pytest.approx(0.045) and d[0].osservato == 0
    assert d[-1].osservato == 1.0
    # il penultimo decile prevede 0,845 e non vede nessun giallo
    assert m.scarto_massimo(d) == pytest.approx(0.845)


def test_somme_per_partita():
    s = m.somme([2.0, 4.0, 3.0], [3, 5, 1])
    assert s.partite == 3
    assert s.previsti_medi == pytest.approx(3.0) and s.reali_medi == pytest.approx(3.0)
    assert s.errore_medio == pytest.approx((1 + 1 + 2) / 3)
    assert -1 <= s.correlazione <= 1
