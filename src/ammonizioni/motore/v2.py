"""Modello V2: cartellini attesi della partita (λ) divisi fra i giocatori.

1. Livello partita: λ = media del campionato × e^(β·x), con x = arbitro, gialli fatti e
   provocati delle due squadre, derby, campo caldo, posta, squilibrio, precedenti, Liga
   (regressione di Poisson sui totali delle partite, panchina compresa).
2. Livello giocatore: propensione π_i = e^(γ·z_i) (gialli/90 e falli/90 ristretti al ruolo,
   duello, storia, diffida, casa, squadra sfavorita, squadre, arbitro con la squadra,
   subentrante) e quota share_i = π_i·minuti_i / Σ_j π_j·minuti_j su tutta la distinta
   (titolari e panchina pesata con la probabilità di entrare).
3. P(giallo_i) = 1 − e^(−λ·share_i): la somma delle attese della partita torna con λ.

Tutto si calcola dallo snapshot `DatiPartita` (dati prima del calcio d'inizio): stesse
caratteristiche nell'app, nella stima dei pesi e nella prova storica."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ammonizioni.config import COMPETIZIONI, campionato_di
from ammonizioni.motore import subentranti
from ammonizioni.motore.fattori.arbitro import inclinazione_con_squadra
from ammonizioni.motore.fattori.base import _minuti_attesi, tasso_base90
from ammonizioni.motore.fattori.duello import avversario_diretto, fattore_duello
from ammonizioni.motore.fattori.situazione import _soglie_diffida
from ammonizioni.motore.fattori.storia import fattore_storia
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import DatiPartita, RigaPresenza, StatSquadra, Titolare

# restringimenti verso la media del campionato (in partite "finte" alla media)
PRIOR_ARBITRO = 10
PRIOR_SQUADRA = 6
PRIOR_PRECEDENTI = 3
MINUTI_PRIOR_FALLI = 900
# un panchinaro può prendere un giallo anche senza entrare: minuti "finti" di esposizione
MINUTI_PANCHINA = 1.0
MINUTI_SUBENTRO_PREDEFINITI = subentranti.MINUTI_SUBENTRO_PREDEFINITI
LIGA = COMPETIZIONI["liga"]

NOMI_PARTITA = (
    "intercetta", "liga", "arbitro", "squadre_fatti", "squadre_provocati", "derby",
    "campo_caldo", "posta", "squilibrio_quote", "squilibrio_punti", "precedenti",
)
NOMI_GIOCATORE = (
    "ruolo_D", "ruolo_M", "ruolo_F", "tasso", "falli", "duello", "storia", "diffidato",
    "casa", "sfavorita", "squadra_fatti", "avversaria_provoca", "arbitro_squadra",
    "subentrante",
)


@dataclass(frozen=True)
class CoefficientiV2:
    """Pesi del modello V2 con data e campione della stima."""
    partita: dict[str, float]
    giocatore: dict[str, float]
    stimati_il: str = ""
    campione: dict = field(default_factory=dict)  # partite, presenze, stagioni, campionati

    def vettore_partita(self) -> np.ndarray:
        return np.array([float(self.partita.get(n, 0.0)) for n in NOMI_PARTITA])

    def vettore_giocatore(self) -> np.ndarray:
        return np.array([float(self.giocatore.get(n, 0.0)) for n in NOMI_GIOCATORE])

    def come_json(self) -> dict:
        return {
            "partita": dict(self.partita), "giocatore": dict(self.giocatore),
            "stimati_il": self.stimati_il, "campione": dict(self.campione),
        }

    @staticmethod
    def da_json(valore) -> "CoefficientiV2 | None":
        """None se il valore salvato non è valido (mai bloccare il motore)."""
        if not isinstance(valore, dict):
            return None
        try:
            partita = {str(k): float(v) for k, v in dict(valore["partita"]).items()}
            giocatore = {str(k): float(v) for k, v in dict(valore["giocatore"]).items()}
        except (KeyError, TypeError, ValueError):
            return None
        if not all(map(math.isfinite, [*partita.values(), *giocatore.values()])):
            return None
        return CoefficientiV2(
            partita, giocatore, str(valore.get("stimati_il", "")),
            dict(valore.get("campione") or {}),
        )


@dataclass(frozen=True)
class Giocatori:
    """Caratteristiche di tutta la distinta (titolari e panchina, portieri compresi)."""
    ids: list[int]
    squadre: list[int]
    titolare: list[bool]
    Z: np.ndarray  # (giocatori, len(NOMI_GIOCATORE))
    log_minuti: np.ndarray  # log dei minuti attesi / 90


@dataclass(frozen=True)
class PrevisioneV2:
    lambda_partita: float
    quote: dict[int, float]  # giocatore -> share (somma 1 sulla distinta)
    probabilita: dict[int, float]


def _log_rapporto(valore: float, media: float) -> float:
    if valore <= 0 or media <= 0:
        return 0.0
    return math.log(valore / media)


def _ristretto(somma: float, n: float, media: float, prior: float) -> float:
    return (somma + prior * media) / (n + prior)


def _squadra(stat: StatSquadra | None, media_squadra: float) -> tuple[float, float]:
    """log(gialli fatti / media), log(gialli provocati / media), ristretti verso la media."""
    if stat is None:
        return 0.0, 0.0
    fatti = _ristretto(stat.gialli_fatti, stat.partite, media_squadra, PRIOR_SQUADRA)
    provocati = _ristretto(stat.gialli_provocati, stat.partite, media_squadra, PRIOR_SQUADRA)
    return _log_rapporto(fatti, media_squadra), _log_rapporto(provocati, media_squadra)


def caratteristiche_partita(dati: DatiPartita) -> tuple[np.ndarray, float]:
    """(x nell'ordine di NOMI_PARTITA, offset = log della media gialli del campionato)."""
    media = dati.medie.gialli_partita
    media_squadra = media / 2
    arbitro = 0.0
    if dati.arbitro is not None and dati.arbitro.partite > 0:
        a = dati.arbitro
        arbitro = _log_rapporto(
            _ristretto(a.gialli_medi * a.partite, a.partite, media, PRIOR_ARBITRO), media
        )
    casa = _squadra(dati.stat_squadre.get(dati.casa_id), media_squadra)
    trasf = _squadra(dati.stat_squadre.get(dati.trasferta_id), media_squadra)
    ctx = dati.contesto
    prob = dati.prob_vittoria
    squilibrio_quote = (
        abs(prob[dati.casa_id] - prob[dati.trasferta_id])
        if dati.casa_id in prob and dati.trasferta_id in prob else 0.0
    )
    punti = ctx.punti_partita
    squilibrio_punti = (
        abs(punti[dati.casa_id] - punti[dati.trasferta_id]) / 3
        if not squilibrio_quote and dati.casa_id in punti and dati.trasferta_id in punti
        else 0.0
    )
    precedenti = 0.0
    if ctx.precedenti_gialli_medi is not None and ctx.precedenti_n > 0:
        precedenti = _log_rapporto(
            _ristretto(ctx.precedenti_gialli_medi * ctx.precedenti_n, ctx.precedenti_n,
                       media, PRIOR_PRECEDENTI),
            media,
        )
    x = np.array([
        1.0,
        1.0 if dati.campionato_id == LIGA else 0.0,
        arbitro,
        (casa[0] + trasf[0]) / 2,
        (casa[1] + trasf[1]) / 2,
        1.0 if ctx.rivalita else 0.0,
        1.0 if ctx.campo_caldo else 0.0,
        float(sum(1 for sq in (dati.casa_id, dati.trasferta_id) if ctx.posta.get(sq))),
        squilibrio_quote,
        squilibrio_punti,
        precedenti,
    ])
    return x, math.log(media)


def _falli90(storico: list[RigaPresenza], media_falli90: float) -> float:
    minuti = sum(r.minuti for r in storico)
    falli = sum(r.falli_commessi for r in storico)
    return (falli + media_falli90 * MINUTI_PRIOR_FALLI / 90) / (minuti + MINUTI_PRIOR_FALLI) * 90


def _minuti_panchinaro(b: Titolare, ruolo: str, storico: list[RigaPresenza], dati, pesi) -> float:
    """Minuti attesi di un panchinaro: probabilità di entrare × minuti medi da subentrato
    (con la tendenza dei cambi della squadra), più MINUTI_PANCHINA."""
    profilo = subentranti.profilo_subentro(b.giocatore_id, ruolo, storico)
    if profilo is None:
        ingresso = subentranti.PROB_INGRESSO_RUOLO.get(ruolo, subentranti.PROB_INGRESSO_RUOLO["M"])
        minuti = MINUTI_SUBENTRO_PREDEFINITI
    else:
        tendenza = subentranti.fattori_tendenza(
            dati.tendenza_cambi.get(b.squadra_id, {}), subentranti.sfavorita(dati, b.squadra_id),
            pesi,
        )
        ingresso = min(1.0, profilo.probabilita_ingresso * tendenza[ruolo])
        minuti = profilo.minuti_medi
    return ingresso * minuti + MINUTI_PANCHINA


def caratteristiche_giocatori(dati: DatiPartita, pesi: Pesi) -> Giocatori:
    """Caratteristiche z e minuti attesi di titolari e panchina (portieri compresi: anche
    loro si dividono i cartellini della partita)."""
    medie = dati.medie
    media_squadra = medie.gialli_partita / 2
    per_id = {t.giocatore_id: t for t in dati.titolari}
    soglie = _soglie_diffida(dati.campionato_id, pesi)
    squadre_stat = {
        sq: _squadra(dati.stat_squadre.get(sq), media_squadra)
        for sq in (dati.casa_id, dati.trasferta_id)
    }
    in_campo = {t.giocatore_id for t in dati.titolari}
    distinta = [(t, True) for t in dati.titolari] + [
        (b, False) for b in dati.panchina if b.giocatore_id not in in_campo
    ]
    ids, squadre, titolare, righe, minuti = [], [], [], [], []
    for g, e_titolare in distinta:
        ruolo = g.ruolo if g.ruolo in medie.per_ruolo else "M"
        storico = dati.storico.get(g.giocatore_id, [])
        storico_lega = [
            r for r in storico if campionato_di(r.competizione_id) in (None, dati.campionato_id)
        ]
        avversaria = dati.trasferta_id if g.squadra_id == dati.casa_id else dati.casa_id
        media_ruolo = medie.per_ruolo[ruolo]
        tasso = tasso_base90(storico_lega, ruolo, medie, dati.stagione, pesi)

        duello = 0.0
        storico_avv: list[RigaPresenza] = []
        avv = None
        if e_titolare:
            compagni = [x for x in dati.titolari if x.squadra_id == g.squadra_id]
            avversari = [x for x in dati.titolari if x.squadra_id != g.squadra_id]
            avv_id = avversario_diretto(
                g, avversari, dati.duelli_manuali.get(g.giocatore_id), compagni=compagni
            )
            avv = per_id.get(avv_id) if avv_id is not None else None
            if avv is not None:
                storico_avv = dati.storico.get(avv.giocatore_id, [])
                duello = math.log(fattore_duello(avv, storico_avv, medie, pesi).valore)
        storia = math.log(fattore_storia(
            storico, avversaria, dati.contesto.rivalita, storico_avv, tasso, pesi,
        ).valore)
        gialli_campionato = sum(
            r.gialli for r in storico_lega
            if r.stagione == dati.stagione and r.competizione_id == dati.campionato_id
        )
        fatti, _ = squadre_stat[g.squadra_id]
        _, provoca = squadre_stat[avversaria]
        righe.append([
            1.0 if ruolo == "D" else 0.0,
            1.0 if ruolo == "M" else 0.0,
            1.0 if ruolo == "F" else 0.0,
            _log_rapporto(tasso, media_ruolo.gialli90),
            _log_rapporto(_falli90(storico_lega, media_ruolo.falli90), media_ruolo.falli90),
            duello,
            storia,
            1.0 if gialli_campionato in soglie else 0.0,
            1.0 if g.squadra_id == dati.casa_id else 0.0,
            1.0 if subentranti.sfavorita(dati, g.squadra_id) else 0.0,
            fatti,
            provoca,
            math.log(max(inclinazione_con_squadra(dati.arbitro, g.squadra_id), 1e-6)),
            0.0 if e_titolare else 1.0,
        ])
        minuti.append(
            _minuti_attesi(storico_lega) if e_titolare
            else _minuti_panchinaro(g, ruolo, storico_lega, dati, pesi)
        )
        ids.append(g.giocatore_id)
        squadre.append(g.squadra_id)
        titolare.append(e_titolare)
    Z = np.array(righe, dtype=float).reshape(len(righe), len(NOMI_GIOCATORE))
    return Giocatori(ids, squadre, titolare, Z, np.log(np.maximum(np.array(minuti), 0.5) / 90))


def prevedi(
    x: np.ndarray, offset: float, giocatori: Giocatori, coeff: CoefficientiV2
) -> PrevisioneV2:
    lam = math.exp(min(float(x @ coeff.vettore_partita()) + offset, 5.0))
    if not giocatori.ids:
        return PrevisioneV2(lam, {}, {})
    eta = giocatori.Z @ coeff.vettore_giocatore() + giocatori.log_minuti
    e = np.exp(eta - eta.max())
    share = e / e.sum()
    prob = 1 - np.exp(-lam * share)
    return PrevisioneV2(
        lam,
        {gid: float(q) for gid, q in zip(giocatori.ids, share)},
        {gid: float(p) for gid, p in zip(giocatori.ids, prob)},
    )


def previsione(dati: DatiPartita, pesi: Pesi, coeff: CoefficientiV2) -> PrevisioneV2:
    x, offset = caratteristiche_partita(dati)
    return prevedi(x, offset, caratteristiche_giocatori(dati, pesi), coeff)


# Pesi predefiniti (neutri finché `scripts/calibra_v2.py` non ne salva di stimati): λ = media
# del campionato e quote proporzionali a gialli/90 × minuti attesi.
COEFFICIENTI_NEUTRI = CoefficientiV2(
    partita={"intercetta": 0.0},
    giocatore={"tasso": 1.0},
    stimati_il="",
    campione={},
)
COEFFICIENTI_PREDEFINITI = COEFFICIENTI_NEUTRI
