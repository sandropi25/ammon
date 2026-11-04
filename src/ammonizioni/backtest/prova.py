"""Prova sulla scorsa stagione: il modello contro la scelta semplice (piu' gialli in stagione).

Per ogni partita Serie A finita con statistiche, il modello vede solo i dati precedenti al
calcio d'inizio e la formazione reale (i titolari della partita)."""
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.formazioni import titolare_da
from ammonizioni.config import COMPETIZIONI
from ammonizioni.db.modelli import Giocatore, Partita, Presenza
from ammonizioni.motore.mercati import MercatoAmmonizioni
from ammonizioni.motore.tipi import Titolare

SERIE_A = COMPETIZIONI["serie_a"]
TITOLARI_MINIMI = 2


@dataclass(frozen=True)
class RisultatoProva:
    partite: int
    successi_modello: int
    successi_base: int
    tasso_modello: float
    tasso_base: float


def _titolari_reali(s: Session, partita: Partita) -> tuple[list[Titolare], dict[int, int]]:
    """Titolari della partita (formazione reale) e gialli presi in quella partita."""
    righe = s.execute(
        select(Presenza, Giocatore)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(Presenza.partita_id == partita.id, Presenza.titolare.is_(True))
        .order_by(Giocatore.id)
    ).all()
    titolari = [titolare_da(g, p.squadra_id, p.griglia, p.ruolo) for p, g in righe]
    gialli = {p.giocatore_id: p.gialli for p, _ in righe}
    return titolari, gialli


def _abbastanza_titolari(titolari: list[Titolare], partita: Partita) -> bool:
    return all(
        sum(1 for t in titolari if t.squadra_id == sq) >= TITOLARI_MINIMI
        for sq in (partita.casa_id, partita.trasferta_id)
    )


def _scelta_semplice(
    s: Session, partita: Partita, titolari: list[Titolare], k: int
) -> list[int]:
    """I k titolari (portieri esclusi) con piu' gialli in Serie A nella stessa stagione prima
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
            Partita.competizione_id == SERIE_A,
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


def prova_stagione(
    s: Session,
    stagione: int,
    k: int = 3,
    avanzamento: Callable[[int, int], None] | None = None,
) -> RisultatoProva:
    partite = s.execute(
        select(Partita)
        .where(
            Partita.competizione_id == SERIE_A,
            Partita.stagione == stagione,
            Partita.stato == "FT",
            Partita.statistiche_scaricate.is_(True),
        )
        .order_by(Partita.data_utc, Partita.id)
    ).scalars().all()

    mercato = MercatoAmmonizioni()
    valutate = successi_modello = successi_base = 0
    for fatte, partita in enumerate(partite, start=1):
        titolari, gialli = _titolari_reali(s, partita)
        if _abbastanza_titolari(titolari, partita):
            valutate += 1
            candidati = mercato.classifica(
                s, partita.id, prima_di=partita.data_utc, titolari=titolari
            )
            if any(gialli.get(c.giocatore_id, 0) >= 1 for c in candidati[:k]):
                successi_modello += 1
            if any(gialli.get(g, 0) >= 1 for g in _scelta_semplice(s, partita, titolari, k)):
                successi_base += 1
        if avanzamento is not None:
            avanzamento(fatte, len(partite))

    return RisultatoProva(
        partite=valutate,
        successi_modello=successi_modello,
        successi_base=successi_base,
        tasso_modello=_tasso(successi_modello, valutate),
        tasso_base=_tasso(successi_base, valutate),
    )
