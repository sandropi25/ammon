"""Prova sulla scorsa stagione: il modello contro la scelta semplice (piu' gialli in stagione).

Per ogni partita Serie A finita con statistiche, il modello vede solo i dati precedenti al
calcio d'inizio e la formazione reale (i titolari della partita)."""
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.formazioni import titolare_da
from ammonizioni.config import COMPETIZIONI, STATI_FINITI
from ammonizioni.db.modelli import Giocatore, Partita, Presenza
from ammonizioni.motore.classifica import classifica, classifica_subentranti
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.pesi import carica_pesi
from ammonizioni.motore.tipi import Titolare

SERIE_A = COMPETIZIONI["serie_a"]
TITOLARI_MINIMI = 2


@dataclass(frozen=True)
class Copertura:
    """Quante partite della prova avevano l'arbitro e la griglia dei titolari."""
    partite: int
    con_arbitro: int
    con_griglia: int


@dataclass(frozen=True)
class RisultatoProva:
    partite: int
    successi_modello: int
    successi_base: int
    tasso_modello: float
    tasso_base: float
    # successi con un subentrante ammonito tra i primi k (0 con `solo_titolari`)
    successi_subentranti: int = 0
    # partite con almeno un subentrante tra i primi k
    partite_con_subentranti: int = 0
    solo_titolari: bool = False


def _titolari_reali(s: Session, partita: Partita) -> tuple[list[Titolare], dict[int, int]]:
    """Titolari della partita (formazione reale) e gialli presi in quella partita."""
    titolari, _, gialli = _distinta_reale(s, partita)
    return titolari, {t.giocatore_id: gialli.get(t.giocatore_id, 0) for t in titolari}


def _distinta_reale(
    s: Session, partita: Partita
) -> tuple[list[Titolare], list[Titolare], dict[int, int]]:
    """Titolari, panchina in distinta (nota prima del calcio d'inizio) e gialli di tutti,
    anche dei subentrati e degli ammoniti dalla panchina. Una sola query."""
    righe = s.execute(
        select(Presenza, Giocatore)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(Presenza.partita_id == partita.id)
        .order_by(Giocatore.id)
    ).all()
    titolari = [titolare_da(g, p.squadra_id, p.griglia, p.ruolo) for p, g in righe if p.titolare]
    panchina = [
        titolare_da(g, p.squadra_id, None, None) for p, g in righe if not p.titolare
    ]
    gialli = {p.giocatore_id: int(p.gialli or 0) for p, _ in righe}
    return titolari, panchina, gialli


def _abbastanza_titolari(titolari: list[Titolare], partita: Partita) -> bool:
    return all(
        sum(1 for t in titolari if t.squadra_id == sq) >= TITOLARI_MINIMI
        for sq in (partita.casa_id, partita.trasferta_id)
    )


def _scelta_semplice(
    s: Session, partita: Partita, titolari: list[Titolare], k: int, competizione_id: int
) -> list[int]:
    """I k titolari (portieri esclusi) con piu' gialli nel campionato nella stessa stagione prima
    della partita; a pari gialli piu' minuti, poi id piu' basso."""
    ids = [t.giocatore_id for t in titolari if t.ruolo != "G"]
    if not ids:
        return []
    righe = s.execute(
        select(
            Presenza.giocatore_id,
            func.coalesce(func.sum(Presenza.gialli), 0),
            func.coalesce(func.sum(Presenza.minuti), 0),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id.in_(ids),
            Partita.competizione_id == competizione_id,
            Partita.stagione == partita.stagione,
            Partita.data_utc < partita.data_utc,
            Partita.id != partita.id,
        )
        .group_by(Presenza.giocatore_id)
    ).all()
    totali = {gid: (int(g), int(m)) for gid, g, m in righe}
    ordinati = sorted(ids, key=lambda gid: (-totali.get(gid, (0, 0))[0], -totali.get(gid, (0, 0))[1], gid))
    return ordinati[:k]


def _tasso(successi: int, partite: int) -> float:
    return successi / partite if partite else 0.0


def _partite_prova(stagione: int, competizione_id: int):
    """Partite finite con statistiche del campionato e della stagione."""
    return select(Partita).where(
        Partita.competizione_id == competizione_id,
        Partita.stagione == stagione,
        Partita.stato.in_(STATI_FINITI),
        Partita.statistiche_scaricate.is_(True),
    )


def copertura(s: Session, stagione: int, competizione_id: int = SERIE_A) -> Copertura:
    """Delle partite effettivamente valutate dalla prova (stesso filtro di `prova_stagione`,
    quindi con almeno 2 titolari per squadra): quante hanno l'arbitro e quante hanno la
    griglia (non nulla) per almeno un titolare. Dice se i fattori arbitro e duello erano attivi."""
    tutte = s.execute(_partite_prova(stagione, competizione_id)).scalars().all()
    partite = [p for p in tutte if _abbastanza_titolari(_titolari_reali(s, p)[0], p)]
    ids_con_griglia = set(
        s.execute(
            select(Presenza.partita_id)
            .where(
                Presenza.partita_id.in_([p.id for p in partite]),
                Presenza.titolare.is_(True),
                Presenza.griglia.is_not(None),
            )
            .distinct()
        ).scalars()
    )
    return Copertura(
        partite=len(partite),
        con_arbitro=sum(1 for p in partite if p.arbitro_id is not None),
        con_griglia=sum(1 for p in partite if p.id in ids_con_griglia),
    )


def prova_stagione(
    s: Session,
    stagione: int,
    k: int = 3,
    avanzamento: Callable[[int, int], None] | None = None,
    competizione_id: int = SERIE_A,
    solo_titolari: bool = False,
) -> RisultatoProva:
    """Con i subentranti (predefinito) i primi k si scelgono fra titolari e probabili
    subentranti (la panchina reale in distinta) per probabilità; `solo_titolari` rifà la
    prova di prima, per confronto."""
    partite = s.execute(
        _partite_prova(stagione, competizione_id).order_by(Partita.data_utc, Partita.id)
    ).scalars().all()

    pesi = carica_pesi(s)
    valutate = successi_modello = successi_base = 0
    successi_subentranti = partite_con_subentranti = 0
    for fatte, partita in enumerate(partite, start=1):
        titolari, panchina, gialli = _distinta_reale(s, partita)
        if _abbastanza_titolari(titolari, partita):
            valutate += 1
            dati = carica_dati(
                s, partita.id, prima_di=partita.data_utc, titolari=titolari,
                panchina=[] if solo_titolari else panchina,
            )
            candidati = classifica(dati, pesi)
            if not solo_titolari:
                # stabile: a pari probabilità il titolare resta davanti
                candidati = sorted(
                    candidati + classifica_subentranti(dati, pesi), key=lambda c: -c.probabilita
                )
            primi = candidati[:k]
            if any(c.subentrante for c in primi):
                partite_con_subentranti += 1
            if any(gialli.get(c.giocatore_id, 0) >= 1 for c in primi):
                successi_modello += 1
                if any(c.subentrante and gialli.get(c.giocatore_id, 0) >= 1 for c in primi):
                    successi_subentranti += 1
            if any(gialli.get(g, 0) >= 1 for g in _scelta_semplice(s, partita, titolari, k, competizione_id)):
                successi_base += 1
        if avanzamento is not None:
            avanzamento(fatte, len(partite))

    return RisultatoProva(
        partite=valutate,
        successi_modello=successi_modello,
        successi_base=successi_base,
        tasso_modello=_tasso(successi_modello, valutate),
        tasso_base=_tasso(successi_base, valutate),
        successi_subentranti=successi_subentranti,
        partite_con_subentranti=partite_con_subentranti,
        solo_titolari=solo_titolari,
    )
