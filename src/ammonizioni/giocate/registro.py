"""Registro delle giocate: inserimento, esiti automatici e statistiche per fonte."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.config import STATI_FINITI
from ammonizioni.db.modelli import Giocata, Partita, Presenza


@dataclass(frozen=True)
class StatFonte:
    fonte: str
    giocate: int  # vinte + perse (rimborsate e in attesa escluse)
    vinte: int
    perse: int
    percentuale_successo: float  # frazione: 0.5 = 50%
    profitto: float
    rendimento: float  # frazione: profitto / somma delle puntate
    prob_implicita_media: float  # media di 1/quota


def aggiungi_giocata(
    s: Session,
    partita_id: int,
    giocatore_id: int,
    fonte: str,
    quota: float,
    puntata: float,
    data: date,
) -> Giocata:
    """Registra una giocata "in_attesa" (flush, commit a carico del chiamante)."""
    if partita_id is None:
        raise ValueError("Seleziona una partita.")
    if giocatore_id is None:
        raise ValueError("Seleziona un giocatore.")
    if quota <= 1:
        raise ValueError("La quota deve essere maggiore di 1.")
    if puntata <= 0:
        raise ValueError("La puntata deve essere maggiore di 0.")
    giocata = Giocata(
        data=data,
        partita_id=partita_id,
        giocatore_id=giocatore_id,
        fonte=fonte,
        quota=quota,
        puntata=puntata,
        esito="in_attesa",
    )
    s.add(giocata)
    s.flush()
    return giocata


def _esito(s: Session, giocata: Giocata, partita: Partita) -> str | None:
    """Esito della giocata, o None se la partita non è ancora decidibile."""
    if partita.stato == "CANC":
        return "rimborsata"
    if partita.stato not in STATI_FINITI or not partita.statistiche_scaricate:
        return None
    presenza = s.get(Presenza, (giocata.partita_id, giocata.giocatore_id))
    if presenza is None or presenza.minuti == 0:
        return "rimborsata"
    # Conta solo il cartellino finale registrato dalla fonte: rosso diretto = persa.
    return "vinta" if presenza.gialli >= 1 else "persa"


def aggiorna_esiti(s: Session) -> int:
    """Chiude le giocate in attesa le cui partite sono decise. Restituisce quante sono
    cambiate (flush, commit a carico del chiamante)."""
    righe = s.execute(
        select(Giocata, Partita)
        .join(Partita, Partita.id == Giocata.partita_id)
        .where(Giocata.esito == "in_attesa")
    ).all()
    cambiate = 0
    for giocata, partita in righe:
        esito = _esito(s, giocata, partita)
        if esito is not None:
            giocata.esito = esito
            cambiate += 1
    s.flush()
    return cambiate


def statistiche_per_fonte(s: Session, partita_ids: set[int] | None = None) -> list[StatFonte]:
    """Statistiche su vinte e perse per ogni fonte, ordinate per nome. Con `partita_ids`
    contano solo le giocate su quelle partite."""
    giocate = s.scalars(select(Giocata).where(Giocata.esito.in_(("vinta", "persa")))).all()
    if partita_ids is not None:
        giocate = [g for g in giocate if g.partita_id in partita_ids]
    per_fonte: dict[str, list[Giocata]] = {}
    for g in giocate:
        per_fonte.setdefault(g.fonte, []).append(g)
    risultato = []
    for fonte in sorted(per_fonte):
        gs = per_fonte[fonte]
        vinte = [g for g in gs if g.esito == "vinta"]
        perse = [g for g in gs if g.esito == "persa"]
        profitto = sum(g.puntata * (g.quota - 1) for g in vinte) - sum(g.puntata for g in perse)
        risultato.append(
            StatFonte(
                fonte=fonte,
                giocate=len(gs),
                vinte=len(vinte),
                perse=len(perse),
                percentuale_successo=len(vinte) / len(gs),
                profitto=profitto,
                rendimento=profitto / sum(g.puntata for g in gs),
                prob_implicita_media=sum(1 / g.quota for g in gs) / len(gs),
            )
        )
    return risultato
