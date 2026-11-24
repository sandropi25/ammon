"""Verifica fuori campione del modello marcatori: si percorrono le partite in ordine di data,
ogni previsione vede solo le partite precedenti (formazioni reali della partita: titolari e
panchina). Confronto con la scelta semplice: gol per 90' nella stagione in corso."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from ammonizioni.backtest import metriche
from ammonizioni.marcatori.modello import PROBABILITA_MASSIMA, Giocante, Parametri, Storico

PARTITE_RISCALDAMENTO = 3  # partite di storico per squadra prima di contare una previsione
PRIMI = 3
NOMI_FATTORI = ("b", "c_forma", "c_derby", "c_rientro", "c_fatica")  # dopo l'intercetta "a"


@dataclass(frozen=True)
class Riga:
    partita_id: int
    competizione_id: int
    stagione: int
    giocatore_id: int
    x: tuple[float, ...]  # Fattori.vettore(): log(attesi), forma, derby, rientro, fatica
    semplice: float  # log(attesi) della scelta semplice
    segnato: bool


def percorri(partite, presenze, parametri: Parametri, derby=None) -> list[Riga]:
    storico = Storico(parametri, derby)
    stagione_gol: dict = {}  # (stagione, campionato, giocatore) -> (gol, minuti)
    righe: list[Riga] = []
    for p in partite:
        lista = presenze.get(p.id, [])
        pronta = min(storico.partite_squadra[p.casa_id], storico.partite_squadra[p.trasferta_id])
        if lista and pronta >= PARTITE_RISCALDAMENTO:
            rosa = [Giocante(x.giocatore_id, x.squadra_id, x.titolare, x.ruolo) for x in lista]
            for gioc, f, pr in zip(rosa, storico.fattori(p, rosa), lista):
                gol, minuti = stagione_gol.get((p.stagione, p.competizione_id, gioc.giocatore_id), (0, 0))
                ritmo = (gol + 0.1) / (minuti / 90 + 1)
                semplice = math.log(max(ritmo * (85 if gioc.titolare else 10) / 90, 1e-4))
                righe.append(Riga(p.id, p.competizione_id, p.stagione, gioc.giocatore_id,
                                  f.vettore(), semplice, pr.gol > 0))
        storico.aggiorna(p, lista)
        for x in lista:
            chiave = (p.stagione, p.competizione_id, x.giocatore_id)
            gol, minuti = stagione_gol.get(chiave, (0, 0))
            stagione_gol[chiave] = (gol + x.gol, minuti + x.minuti)
    return righe


def logistica(x: np.ndarray, y: np.ndarray, l2: float = 1.0, iterazioni: int = 60) -> np.ndarray:
    """Regressione logistica (Newton) con intercetta; l2 leggera sui pesi (non sull'intercetta).
    `x` ha una colonna per fattore; restituisce [intercetta, pesi...]."""
    X = np.column_stack([np.ones(len(x)), x])
    beta = np.zeros(X.shape[1])
    beta[1] = 1.0
    pen = np.full(X.shape[1], l2)
    pen[0] = 0.0
    for _ in range(iterazioni):
        p = 1 / (1 + np.exp(-(X @ beta)))
        g = X.T @ (p - y) + pen * beta
        h = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen) + 1e-9 * np.eye(len(beta))
        passo = np.linalg.solve(h, g)
        beta -= passo
        if np.max(np.abs(passo)) < 1e-9:
            break
    return beta


def _matrice(righe: list[Riga], colonne: int) -> tuple[np.ndarray, np.ndarray]:
    return (np.array([r.x[:colonne] for r in righe], float),
            np.array([r.segnato for r in righe], float))


def prevedi(beta: np.ndarray, x: np.ndarray) -> np.ndarray:
    return np.minimum(1 / (1 + np.exp(-(beta[0] + x @ beta[1:]))), PROBABILITA_MASSIMA)


@dataclass(frozen=True)
class Misure:
    partite: int
    log_loss: float
    brier: float
    scarto_calibrazione: float
    primi_almeno_uno: float  # partite in cui almeno uno dei primi 3 segna
    primo_segna: float  # partite in cui il primo della lista segna


def misura(righe: list[Riga], prob: np.ndarray) -> Misure:
    y = np.array([r.segnato for r in righe], float)
    per_partita: dict[int, list[tuple[float, bool]]] = {}
    for r, q in zip(righe, prob):
        per_partita.setdefault(r.partita_id, []).append((float(q), r.segnato))
    primi = primo = 0
    for lista in per_partita.values():
        ordinata = sorted(lista, key=lambda t: -t[0])
        primi += any(s for _, s in ordinata[:PRIMI])
        primo += ordinata[0][1]
    n = len(per_partita) or 1
    return Misure(
        len(per_partita), metriche.log_loss(prob, y), metriche.brier(prob, y),
        metriche.scarto_massimo(metriche.decili(prob, y)), primi / n, primo / n,
    )


def stima(righe: list[Riga], parametri: Parametri, colonne: int = 5) -> Parametri:
    """Calibrazione (intercetta e pesi dei fattori) sulle righe; fattori oltre `colonne` a 0."""
    beta = logistica(*_matrice(righe, colonne))
    valori = {"a": float(beta[0])}
    for nome, v in zip(NOMI_FATTORI, beta[1:]):
        valori[nome] = float(v)
    for nome in NOMI_FATTORI[colonne:]:
        valori[nome] = 0.0
    return replace(parametri, **valori)


def confronta(allenamento: list[Riga], prova: list[Riga], colonne: int = 5):
    """Misure sulla prova di: modello solo attesi, modello con i fattori, scelta semplice;
    ogni metodo calibrato sull'allenamento. Restituisce anche i pesi del modello completo."""
    risultati = {}
    for nome, c in (("solo attesi", 1), ("con fattori", colonne)):
        beta = logistica(*_matrice(allenamento, c))
        risultati[nome] = misura(prova, prevedi(beta, _matrice(prova, c)[0]))
        if c == colonne:
            pesi = beta
    xs = np.array([[r.semplice] for r in allenamento])
    ys = np.array([r.segnato for r in allenamento], float)
    beta_s = logistica(xs, ys)
    risultati["scelta semplice"] = misura(prova, prevedi(beta_s, np.array([[r.semplice] for r in prova])))
    return risultati, pesi
