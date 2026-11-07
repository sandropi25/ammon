"""Regressioni piccole per il modello V2, solo numpy (metodo di Newton / IRLS).

- `poisson`: conteggi con collegamento log (cartellini attesi della partita);
- `logistica`: esiti 0/1 (ricalibrazione di Platt);
- `multinomiale_condizionale`: come si dividono i cartellini di una partita fra i giocatori
  (logit condizionale: l'equivalente della Poisson con un effetto fisso per partita).

Tutte hanno una penalità L2 (`l2`) sui coefficienti diversi dall'intercetta (colonna 0 se
`intercetta=True`): con pochi dati tiene i pesi vicini a 0 invece di farli esplodere."""
from __future__ import annotations

import numpy as np

ITERAZIONI_MASSIME = 100
TOLLERANZA = 1e-9


def _penalita(k: int, l2: float, intercetta: bool) -> np.ndarray:
    p = np.full(k, float(l2))
    if intercetta and k:
        p[0] = 0.0
    return p


def _newton(
    obiettivo, beta: np.ndarray, iterazioni: int = ITERAZIONI_MASSIME, tol: float = TOLLERANZA
) -> np.ndarray:
    """Massimizza `obiettivo(beta) -> (valore, gradiente, hessiana negativa)` con passi di
    Newton dimezzati finché il valore non migliora."""
    valore, grad, h = obiettivo(beta)
    for _ in range(iterazioni):
        passo = np.linalg.solve(h + 1e-12 * np.eye(len(beta)), grad)
        t = 1.0
        while True:
            nuovo = beta + t * passo
            v_nuovo, g_nuovo, h_nuovo = obiettivo(nuovo)
            if np.isfinite(v_nuovo) and v_nuovo >= valore - 1e-12:
                break
            t /= 2
            if t < 1e-10:
                return beta
        miglioramento = v_nuovo - valore
        beta, valore, grad, h = nuovo, v_nuovo, g_nuovo, h_nuovo
        if np.max(np.abs(t * passo)) < tol or abs(miglioramento) < tol * (1 + abs(valore)):
            break
    return beta


def poisson(
    X: np.ndarray,
    y: np.ndarray,
    offset: np.ndarray | None = None,
    pesi: np.ndarray | None = None,
    l2: float = 0.0,
    intercetta: bool = True,
) -> np.ndarray:
    """Coefficienti di log E[y] = X·beta + offset (massima verosimiglianza penalizzata)."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    n, k = X.shape
    off = np.zeros(n) if offset is None else np.asarray(offset, float)
    w = np.ones(n) if pesi is None else np.asarray(pesi, float)
    pen = _penalita(k, l2, intercetta)

    def obiettivo(beta):
        eta = np.clip(X @ beta + off, -30, 30)
        mu = np.exp(eta)
        valore = float(np.sum(w * (y * eta - mu)) - 0.5 * np.sum(pen * beta**2))
        grad = X.T @ (w * (y - mu)) - pen * beta
        h = (X * (w * mu)[:, None]).T @ X + np.diag(pen)
        return valore, grad, h

    beta0 = np.zeros(k)
    if intercetta and k:
        media = np.sum(w * y) / max(np.sum(w * np.exp(off)), 1e-12)
        beta0[0] = np.log(max(media, 1e-9))
    return _newton(obiettivo, beta0)


def logistica(
    X: np.ndarray,
    y: np.ndarray,
    pesi: np.ndarray | None = None,
    l2: float = 0.0,
    intercetta: bool = True,
) -> np.ndarray:
    """Coefficienti di logit P(y=1) = X·beta."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    n, k = X.shape
    w = np.ones(n) if pesi is None else np.asarray(pesi, float)
    pen = _penalita(k, l2, intercetta)

    def obiettivo(beta):
        eta = np.clip(X @ beta, -30, 30)
        p = 1 / (1 + np.exp(-eta))
        valore = float(
            np.sum(w * (y * eta - np.logaddexp(0, eta))) - 0.5 * np.sum(pen * beta**2)
        )
        grad = X.T @ (w * (y - p)) - pen * beta
        h = (X * (w * p * (1 - p))[:, None]).T @ X + np.diag(pen)
        return valore, grad, h

    return _newton(obiettivo, np.zeros(k))


def multinomiale_condizionale(
    Z: np.ndarray,
    log_esposizione: np.ndarray,
    y: np.ndarray,
    gruppi: np.ndarray,
    l2: float = 0.0,
) -> np.ndarray:
    """Coefficienti gamma della quota q_i = e^(z_i·gamma + log_esp_i) / somma del gruppo,
    con i conteggi y_i del gruppo distribuiti in proporzione alle quote. Niente intercetta
    (si semplifica nella quota): tutte le colonne sono penalizzate."""
    Z = np.asarray(Z, float)
    y = np.asarray(y, float)
    le = np.asarray(log_esposizione, float)
    _, g = np.unique(np.asarray(gruppi), return_inverse=True)
    n_gruppi = int(g.max()) + 1 if len(g) else 0
    totali = np.bincount(g, weights=y, minlength=n_gruppi)  # cartellini di ogni gruppo
    k = Z.shape[1]
    pen = np.full(k, float(l2))

    def obiettivo(gamma):
        eta = Z @ gamma + le
        massimo = np.full(n_gruppi, -np.inf)
        np.maximum.at(massimo, g, eta)
        e = np.exp(eta - massimo[g])
        somma = np.bincount(g, weights=e, minlength=n_gruppi)
        q = e / somma[g]
        log_somma = np.log(somma) + massimo
        valore = float(np.sum(y * eta) - np.sum(totali * log_somma) - 0.5 * np.sum(pen * gamma**2))
        medie = np.zeros((n_gruppi, k))
        np.add.at(medie, g, q[:, None] * Z)  # media delle z del gruppo pesata con le quote
        grad = Z.T @ y - totali @ medie - pen * gamma
        pesi_righe = totali[g] * q
        h = (Z * pesi_righe[:, None]).T @ Z - (medie * totali[:, None]).T @ medie + np.diag(pen)
        return valore, grad, h

    return _newton(obiettivo, np.zeros(k))


def quote_gruppo(eta: np.ndarray, gruppi: np.ndarray) -> np.ndarray:
    """Quote softmax di `eta` dentro ogni gruppo (somma 1 per gruppo)."""
    eta = np.asarray(eta, float)
    _, g = np.unique(np.asarray(gruppi), return_inverse=True)
    n_gruppi = int(g.max()) + 1 if len(g) else 0
    massimo = np.full(n_gruppi, -np.inf)
    np.maximum.at(massimo, g, eta)
    e = np.exp(eta - massimo[g])
    return e / np.bincount(g, weights=e, minlength=n_gruppi)[g]
