"""Stima e prova del modello V2 contro V1 e la scelta semplice.

`estrai` legge una volta ogni partita finita (dati prima del calcio d'inizio, distinta
reale): caratteristiche V2, probabilità V1, scelta semplice e gialli reali. `stima` calcola
i coefficienti V2 su un elenco di partite, `valuta` misura i tre metodi su un altro."""
from __future__ import annotations

import pickle
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from ammonizioni.backtest import metriche
from ammonizioni.backtest.prova import (
    _abbastanza_titolari,
    _distinta_reale,
    _partite_prova,
    _scelta_semplice,
)
from ammonizioni.db.modelli import Partita
from ammonizioni.motore import regressione, v2
from ammonizioni.motore.classifica import classifica, classifica_subentranti
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.pesi import Pesi

L2_PARTITA = 2.0
L2_GIOCATORE = 2.0
K_SCELTA_SEMPLICE = 3


@dataclass
class PartitaProva:
    partita_id: int
    campionato: int
    stagione: int
    x: np.ndarray
    offset: float
    ids: np.ndarray  # distinta (titolari e panchina)
    Z: np.ndarray
    log_minuti: np.ndarray
    gialli: np.ndarray  # gialli reali di ogni giocatore della distinta (panchina compresa)
    candidati_v1: list[int]  # candidati di V1 nell'ordine di V1 (titolari e subentranti)
    p_v1: list[float]
    semplice: list[int] = field(default_factory=list)  # primi 3 della scelta semplice

    @property
    def gialli_totali(self) -> int:
        return int(self.gialli.sum())


def estrai_partita(s: Session, partita: Partita, pesi: Pesi) -> PartitaProva | None:
    titolari, panchina, gialli = _distinta_reale(s, partita)
    if not _abbastanza_titolari(titolari, partita):
        return None
    dati = carica_dati(s, partita.id, prima_di=partita.data_utc, titolari=titolari,
                       panchina=panchina)
    # come la prova di V1: stabile, a pari probabilità il titolare resta davanti
    v1 = sorted(
        classifica(dati, pesi) + classifica_subentranti(dati, pesi), key=lambda c: -c.probabilita
    )
    x, offset = v2.caratteristiche_partita(dati)
    g = v2.caratteristiche_giocatori(dati, pesi)
    # chi ha un giallo ma non è nella distinta caricata (non dovrebbe succedere) resta fuori
    # da Z: lo aggiungiamo al totale come giocatore a esposizione minima per non perderlo
    ids = list(g.ids)
    Z, log_minuti = g.Z, g.log_minuti
    mancanti = [gid for gid, n in gialli.items() if n and gid not in set(ids)]
    if mancanti:
        ids += mancanti
        Z = np.vstack([Z, np.zeros((len(mancanti), Z.shape[1]))])
        log_minuti = np.concatenate([log_minuti, np.full(len(mancanti), np.log(0.5 / 90))])
    return PartitaProva(
        partita_id=partita.id,
        campionato=partita.competizione_id,
        stagione=partita.stagione,
        x=x,
        offset=offset,
        ids=np.array(ids, dtype=np.int64),
        Z=Z,
        log_minuti=log_minuti,
        gialli=np.array([gialli.get(gid, 0) for gid in ids], dtype=float),
        candidati_v1=[c.giocatore_id for c in v1],
        p_v1=[c.probabilita for c in v1],
        semplice=_scelta_semplice(s, partita, titolari, K_SCELTA_SEMPLICE, partita.competizione_id),
    )


def estrai(
    s: Session,
    stagione: int,
    competizione_id: int,
    pesi: Pesi | None = None,
    avanzamento: Callable[[int, int], None] | None = None,
) -> list[PartitaProva]:
    pesi = pesi or Pesi()
    partite = s.execute(
        _partite_prova(stagione, competizione_id).order_by(Partita.data_utc, Partita.id)
    ).scalars().all()
    risultato = []
    for fatte, partita in enumerate(partite, start=1):
        riga = estrai_partita(s, partita, pesi)
        if riga is not None:
            risultato.append(riga)
        if avanzamento is not None:
            avanzamento(fatte, len(partite))
    return risultato


def estrai_con_cache(
    s: Session,
    stagione: int,
    competizione_id: int,
    cartella: Path | None,
    avanzamento: Callable[[int, int], None] | None = None,
) -> list[PartitaProva]:
    """Come `estrai`, ma salva/rilegge il risultato in `cartella` (file locale dello script:
    la lettura di una partita richiede tempo, la stima no)."""
    if cartella is None:
        return estrai(s, stagione, competizione_id, avanzamento=avanzamento)
    file = Path(cartella) / f"v2_{competizione_id}_{stagione}.pkl"
    if file.exists():
        with file.open("rb") as f:
            return pickle.load(f)
    partite = estrai(s, stagione, competizione_id, avanzamento=avanzamento)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("wb") as f:
        pickle.dump(partite, f)
    return partite


def stima(
    partite: list[PartitaProva],
    l2_partita: float = L2_PARTITA,
    l2_giocatore: float = L2_GIOCATORE,
    platt: bool = True,
) -> v2.CoefficientiV2:
    if not partite:
        raise ValueError("Nessuna partita per la stima")
    X = np.vstack([p.x for p in partite])
    y = np.array([p.gialli_totali for p in partite], float)
    offset = np.array([p.offset for p in partite])
    beta = regressione.poisson(X, y, offset=offset, l2=l2_partita)

    Z = np.vstack([p.Z for p in partite])
    log_minuti = np.concatenate([p.log_minuti for p in partite])
    gialli = np.concatenate([p.gialli for p in partite])
    gruppi = np.concatenate([np.full(len(p.ids), i) for i, p in enumerate(partite)])
    gamma = regressione.multinomiale_condizionale(Z, log_minuti, gialli, gruppi, l2=l2_giocatore)
    grezzi = v2.CoefficientiV2(
        partita={n: float(b) for n, b in zip(v2.NOMI_PARTITA, beta)},
        giocatore={n: float(c) for n, c in zip(v2.NOMI_GIOCATORE, gamma)},
    )
    calibrazione: dict[str, float] = {}
    if platt:
        # Platt sui candidati (quelli che l'app mostra): logit P = a + b·log(λ·share)
        log_mu, esiti = [], []
        for p in partite:
            lam, _ = probabilita_v2(p, grezzi)
            quote = _quote(p, grezzi)
            gialli_p = {int(gid): n for gid, n in zip(p.ids, p.gialli)}
            for gid in p.candidati_v1:
                log_mu.append(np.log(max(lam * quote[gid], 1e-12)))
                esiti.append(1.0 if gialli_p.get(gid, 0) >= 1 else 0.0)
        if esiti and 0 < sum(esiti) < len(esiti):
            ab = regressione.logistica(np.column_stack([np.ones(len(log_mu)), log_mu]), esiti)
            calibrazione = {"a": float(ab[0]), "b": float(ab[1])}
    return v2.CoefficientiV2(
        partita={n: float(b) for n, b in zip(v2.NOMI_PARTITA, beta)},
        giocatore={n: float(c) for n, c in zip(v2.NOMI_GIOCATORE, gamma)},
        stimati_il=date.today().isoformat(),
        campione={
            "partite": len(partite),
            "presenze": int(len(gialli)),
            "gialli": int(gialli.sum()),
            "stagioni": sorted({p.stagione for p in partite}),
            "campionati": sorted({p.campionato for p in partite}),
            "l2": [l2_partita, l2_giocatore],
        },
        calibrazione=calibrazione,
    )


def _previsione(p: PartitaProva, coeff: v2.CoefficientiV2) -> v2.PrevisioneV2:
    g = v2.Giocatori(list(map(int, p.ids)), [], [], p.Z, p.log_minuti)
    return v2.prevedi(p.x, p.offset, g, coeff)


def _quote(p: PartitaProva, coeff: v2.CoefficientiV2) -> dict[int, float]:
    return _previsione(p, coeff).quote


def probabilita_v2(p: PartitaProva, coeff: v2.CoefficientiV2) -> tuple[float, dict[int, float]]:
    prev = _previsione(p, coeff)
    return prev.lambda_partita, prev.probabilita


@dataclass(frozen=True)
class MisureMetodo:
    nome: str
    partite: int
    successi: int
    tasso: float
    brier: float | None = None
    log_loss: float | None = None
    decili: list[metriche.Decile] | None = None
    scarto_decili: float | None = None
    somme: metriche.Somme | None = None


@dataclass(frozen=True)
class Valutazione:
    v1: MisureMetodo
    v2: MisureMetodo
    semplice: MisureMetodo
    lambda_somme: metriche.Somme  # λ di V2 contro i gialli reali della partita
    gialli_candidati_medi: float = 0.0  # gialli reali dei soli candidati, per partita
    v2_grezzo: MisureMetodo | None = None  # V2 senza ricalibrazione di Platt


def _misure(nome, primi, prob, esiti, somme_prev, reali) -> MisureMetodo:
    successi = sum(primi)
    n = len(primi)
    d = metriche.decili(prob, esiti)
    return MisureMetodo(
        nome, n, successi, successi / n if n else 0.0,
        metriche.brier(prob, esiti), metriche.log_loss(prob, esiti), d,
        metriche.scarto_massimo(d), metriche.somme(somme_prev, reali),
    )


def _num(x: float | None, cifre: int = 3) -> str:
    return "–" if x is None else f"{x:.{cifre}f}".replace(".", ",")


def _pct(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",") + "%"


def testo_valutazione(val: Valutazione, titolo: str, k: int = 3) -> str:
    """Tabelle in Markdown (leggibili anche nel terminale) di una valutazione."""
    righe = [
        f"### {titolo}",
        "",
        f"| Metodo | Partite | Primi {k} | Tasso | Brier | Log-loss | Scarto max decili "
        "| Σp per partita | Gialli reali | Errore medio Σp |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in (val.v1, val.v2, val.v2_grezzo, val.semplice):
        if m is None:
            continue
        s = m.somme
        righe.append(
            f"| {m.nome} | {m.partite} | {m.successi} | {_pct(m.tasso)} | {_num(m.brier, 4)} "
            f"| {_num(m.log_loss, 4)} "
            f"| {'–' if m.scarto_decili is None else _num(m.scarto_decili * 100, 1) + ' punti'} "
            f"| {_num(s.previsti_medi if s else None, 2)} | {_num(s.reali_medi if s else None, 2)} "
            f"| {_num(s.errore_medio if s else None, 2)} |"
        )
    lam = val.lambda_somme
    righe += [
        "",
        f"λ di V2 (gialli attesi della partita, tutta la distinta): media {_num(lam.previsti_medi, 2)}"
        f" contro {_num(lam.reali_medi, 2)} reali, errore medio {_num(lam.errore_medio, 2)},"
        f" correlazione {_num(lam.correlazione, 3)}.",
        f"Gialli reali dei soli candidati (portieri e panchinari sotto soglia esclusi): "
        f"{_num(val.gialli_candidati_medi, 2)} per partita.",
        "",
        "Calibrazione per decili (previsto / osservato, in %):",
        "",
        "| Decile | V1 previsto | V1 osservato | V2 previsto | V2 osservato |",
        "|---|---|---|---|---|",
    ]
    for i, (a, b) in enumerate(zip(val.v1.decili or [], val.v2.decili or []), start=1):
        righe.append(
            f"| {i} | {_num(a.previsto * 100, 1)} | {_num(a.osservato * 100, 1)} "
            f"| {_num(b.previsto * 100, 1)} | {_num(b.osservato * 100, 1)} |"
        )
    return "\n".join(righe) + "\n"


def testo_coefficienti(coeff: v2.CoefficientiV2) -> str:
    righe = [
        f"Stimati il {coeff.stimati_il} · campione {coeff.campione}",
        "",
        "| Livello partita (λ) | coefficiente |",
        "|---|---|",
        *[f"| {n} | {_num(coeff.partita.get(n, 0.0), 3)} |" for n in v2.NOMI_PARTITA],
        "",
        "| Livello giocatore (quota) | coefficiente |",
        "|---|---|",
        *[f"| {n} | {_num(coeff.giocatore.get(n, 0.0), 3)} |" for n in v2.NOMI_GIOCATORE],
        "",
        "Ricalibrazione di Platt (logit P = a + b·log λ·share): "
        + (
            f"a = {_num(coeff.calibrazione['a'], 3)}, b = {_num(coeff.calibrazione['b'], 3)}"
            if coeff.calibrazione else "nessuna (P = 1 − e^(−λ·share))"
        ),
    ]
    return "\n".join(righe) + "\n"


def valuta(partite: list[PartitaProva], coeff: v2.CoefficientiV2, k: int = 3) -> Valutazione:
    """Primi k, Brier, log-loss, decili e somme sui candidati di V1 (titolari e probabili
    subentranti, portieri esclusi): stesso insieme per V1 e V2. I gialli reali della partita
    contano tutta la distinta."""
    v1_primi, v2_primi, semplice_primi = [], [], []
    p1, p2, pg, esiti = [], [], [], []
    somme1, somme2, sommeg, reali, reali_candidati, lambdas = [], [], [], [], [], []
    grezzi = coeff.senza_calibrazione()
    for p in partite:
        gialli = {int(gid): n for gid, n in zip(p.ids, p.gialli)}
        lam, prob = probabilita_v2(p, coeff)
        _, prob_g = probabilita_v2(p, grezzi)
        cand = p.candidati_v1
        if not cand:
            continue
        posizione = {gid: i for i, gid in enumerate(cand)}
        ordine_v2 = sorted(cand, key=lambda gid: (-prob.get(gid, 0.0), posizione[gid]))
        v1_primi.append(any(gialli.get(g, 0) >= 1 for g in cand[:k]))
        v2_primi.append(any(gialli.get(g, 0) >= 1 for g in ordine_v2[:k]))
        semplice_primi.append(any(gialli.get(g, 0) >= 1 for g in p.semplice[:k]))
        q2 = [prob.get(g, 0.0) for g in cand]
        qg = [prob_g.get(g, 0.0) for g in cand]
        p1 += p.p_v1
        p2 += q2
        pg += qg
        esiti += [1.0 if gialli.get(g, 0) >= 1 else 0.0 for g in cand]
        somme1.append(sum(p.p_v1))
        somme2.append(sum(q2))
        sommeg.append(sum(qg))
        reali.append(p.gialli_totali)
        reali_candidati.append(sum(gialli.get(g, 0) for g in cand))
        lambdas.append(lam)
    n = len(semplice_primi)
    return Valutazione(
        v1=_misure("V1", v1_primi, p1, esiti, somme1, reali),
        v2=_misure("V2", v2_primi, p2, esiti, somme2, reali),
        # stessa classifica di V2 (Platt è monotona), probabilità 1 − e^(−λ·share)
        v2_grezzo=_misure("V2 senza Platt", v2_primi, pg, esiti, sommeg, reali),
        semplice=MisureMetodo(
            "Scelta semplice", n, sum(semplice_primi), sum(semplice_primi) / n if n else 0.0
        ),
        lambda_somme=metriche.somme(lambdas, reali),
        gialli_candidati_medi=float(np.mean(reali_candidati)) if reali_candidati else 0.0,
    )
