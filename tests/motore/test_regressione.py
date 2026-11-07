import numpy as np
import pytest

from ammonizioni.motore import regressione as rg


def test_poisson_solo_intercetta_e_il_logaritmo_della_media():
    y = np.array([0, 1, 2, 3, 4, 2])
    beta = rg.poisson(np.ones((6, 1)), y)
    assert beta[0] == pytest.approx(np.log(y.mean()), abs=1e-8)


def test_poisson_con_offset():
    y = np.array([2, 4, 6, 8])
    esposizione = np.array([1.0, 2.0, 3.0, 4.0])  # tasso costante 2
    beta = rg.poisson(np.ones((4, 1)), y, offset=np.log(esposizione))
    assert beta[0] == pytest.approx(np.log(2.0), abs=1e-8)


def test_poisson_ritrova_i_coefficienti_simulati():
    rng = np.random.default_rng(1)
    n = 20000
    X = np.column_stack([np.ones(n), rng.normal(size=n), rng.integers(0, 2, n)])
    vero = np.array([0.8, 0.3, -0.2])
    y = rng.poisson(np.exp(X @ vero))
    beta = rg.poisson(X, y)
    assert beta == pytest.approx(vero, abs=0.03)


def test_poisson_l2_restringe_verso_zero_ma_non_l_intercetta():
    rng = np.random.default_rng(2)
    n = 200
    X = np.column_stack([np.ones(n), rng.normal(size=n)])
    y = rng.poisson(np.exp(1.0 + 0.5 * X[:, 1]))
    libero = rg.poisson(X, y)
    penalizzato = rg.poisson(X, y, l2=1e6)
    assert abs(penalizzato[1]) < 1e-3 < abs(libero[1])
    assert penalizzato[0] == pytest.approx(np.log(y.mean()), abs=1e-3)


def test_logistica_ritrova_i_coefficienti_simulati():
    rng = np.random.default_rng(3)
    n = 30000
    X = np.column_stack([np.ones(n), rng.normal(size=n)])
    vero = np.array([-1.5, 0.7])
    y = rng.random(n) < 1 / (1 + np.exp(-(X @ vero)))
    beta = rg.logistica(X, y.astype(float))
    assert beta == pytest.approx(vero, abs=0.05)


def test_logistica_solo_intercetta():
    y = np.array([1, 0, 0, 0], float)
    beta = rg.logistica(np.ones((4, 1)), y)
    assert 1 / (1 + np.exp(-beta[0])) == pytest.approx(0.25, abs=1e-8)


def _simula_gruppi(rng, gruppi, per_gruppo, gamma):
    n = gruppi * per_gruppo
    Z = rng.normal(size=(n, len(gamma)))
    esp = rng.uniform(0.2, 1.0, n)
    g = np.repeat(np.arange(gruppi), per_gruppo)
    totali = rng.poisson(4.0, gruppi)
    q = rg.quote_gruppo(Z @ gamma + np.log(esp), g)
    y = np.zeros(n)
    for k in range(gruppi):
        righe = np.flatnonzero(g == k)
        y[righe] = rng.multinomial(totali[k], q[righe])
    return Z, np.log(esp), y, g


def test_multinomiale_condizionale_ritrova_i_coefficienti():
    rng = np.random.default_rng(4)
    vero = np.array([0.6, -0.4])
    Z, le, y, g = _simula_gruppi(rng, 3000, 20, vero)
    gamma = rg.multinomiale_condizionale(Z, le, y, g)
    assert gamma == pytest.approx(vero, abs=0.05)


def test_multinomiale_condizionale_uguale_alla_poisson_con_effetti_fissi():
    rng = np.random.default_rng(5)
    Z, le, y, g = _simula_gruppi(rng, 30, 8, np.array([0.5]))
    gamma = rg.multinomiale_condizionale(Z, le, y, g)
    con_gialli = np.bincount(g, weights=y) > 0  # i gruppi senza cartellini non contano
    righe = con_gialli[g]
    dummy = (g[righe, None] == np.flatnonzero(con_gialli)[None, :]).astype(float)
    beta = rg.poisson(
        np.column_stack([Z[righe], dummy]), y[righe], offset=le[righe], intercetta=False
    )
    assert gamma[0] == pytest.approx(beta[0], abs=1e-6)


def test_quote_gruppo_sommano_a_uno():
    q = rg.quote_gruppo(np.array([0.0, 1.0, 2.0, 5.0, 5.0]), np.array([7, 7, 7, 3, 3]))
    assert q[:3].sum() == pytest.approx(1.0)
    assert q[3:] == pytest.approx([0.5, 0.5])
