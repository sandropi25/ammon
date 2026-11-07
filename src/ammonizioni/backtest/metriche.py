"""Misure della prova: Brier, log-loss, calibrazione per decili, somme per partita."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MINIMO_LOG = 1e-6


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2)) if len(p) else float("nan")


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, float), MINIMO_LOG, 1 - MINIMO_LOG)
    y = np.asarray(y, float)
    if not len(p):
        return float("nan")
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


@dataclass(frozen=True)
class Decile:
    n: int
    previsto: float
    osservato: float


def decili(p, y, gruppi: int = 10) -> list[Decile]:
    """Previsioni ordinate e divise in `gruppi` parti uguali (per numero): media prevista e
    frequenza osservata di ciascuna."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    ordine = np.argsort(p, kind="stable")
    risultato = []
    for parte in np.array_split(ordine, gruppi):
        if len(parte):
            risultato.append(Decile(len(parte), float(p[parte].mean()), float(y[parte].mean())))
    return risultato


def scarto_massimo(d: list[Decile]) -> float:
    """Il massimo |previsto − osservato| fra i decili (in probabilità, 0,03 = 3 punti)."""
    return max((abs(x.previsto - x.osservato) for x in d), default=float("nan"))


@dataclass(frozen=True)
class Somme:
    partite: int
    previsti_medi: float  # somma delle probabilità per partita, media
    reali_medi: float  # gialli reali per partita, media (tutta la distinta)
    errore_medio: float  # media di |previsti − reali|
    correlazione: float


def somme(previsti, reali) -> Somme:
    a, b = np.asarray(previsti, float), np.asarray(reali, float)
    if not len(a):
        nan = float("nan")
        return Somme(0, nan, nan, nan, nan)
    corr = float(np.corrcoef(a, b)[0, 1]) if len(a) > 1 and a.std() > 0 and b.std() > 0 else 0.0
    return Somme(len(a), float(a.mean()), float(b.mean()), float(np.mean(np.abs(a - b))), corr)
