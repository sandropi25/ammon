"""Stemmi e colori delle squadre (ESPN): salvati sulle squadre durante i caricamenti del
calendario e delle statistiche, senza richieste in più; più un riempimento una tantum per
le squadre già nel database."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.config import CAMPIONATI, STAGIONE_CORRENTE
from ammonizioni.db.modelli import Squadra
from ammonizioni.fonti.tipi import PartitaDati, StileSquadra

log = logging.getLogger(__name__)


def campi_stile(stile: StileSquadra | None) -> dict[str, str]:
    """Campi di `Squadra` da scrivere: solo quelli noti (un dato mancante non cancella
    quello già salvato)."""
    if stile is None:
        return {}
    campi = {"logo_url": stile.logo_url, "colore": stile.colore, "colore_alt": stile.colore_alt}
    return {k: v for k, v in campi.items() if v}


def stili_partite(partite: list[PartitaDati]) -> dict[int, StileSquadra]:
    """Stile di ogni squadra che compare nelle partite (l'ultimo visto vince)."""
    stili: dict[int, StileSquadra] = {}
    for p in partite:
        for squadra_id, stile in ((p.casa_id, p.casa_stile), (p.trasferta_id, p.trasferta_stile)):
            if stile is not None:
                stili[squadra_id] = stile
    return stili


def salva_stili(s: Session, stili: dict[int, StileSquadra]) -> int:
    """Aggiorna stemma e colori delle squadre già nel database (una query per tutte);
    le squadre sconosciute si saltano. Restituisce quante squadre sono cambiate."""
    if not stili:
        return 0
    cambiate = 0
    for squadra in s.scalars(select(Squadra).where(Squadra.id.in_(list(stili)))):
        campi = campi_stile(stili[squadra.id])
        if any(getattr(squadra, k) != v for k, v in campi.items()):
            for k, v in campi.items():
                setattr(squadra, k, v)
            cambiate += 1
    s.flush()
    return cambiate


def salva_stili_fonte(s: Session, fonte) -> int:
    """Stili che la fonte ha letto nei summary (ESPN `stili_squadre`), se li sa dare."""
    leggi = getattr(fonte, "stili_squadre", None)
    if not callable(leggi):
        return 0
    stili = leggi()
    return salva_stili(s, stili) if isinstance(stili, dict) else 0


def riempi_stemmi(
    s: Session,
    fonte,
    stagione: int = STAGIONE_CORRENTE,
    campionati: tuple[int, ...] = tuple(CAMPIONATI),
) -> int:
    """Riempimento una tantum per le squadre già salvate: legge il calendario di ogni
    campionato (2 richieste ESPN per campionato) e ne salva solo stemmi e colori, senza
    toccare le partite. Restituisce quante squadre sono cambiate (commit incluso)."""
    stili: dict[int, StileSquadra] = {}
    for campionato in campionati:
        stili.update(stili_partite(fonte.partite(campionato, stagione)))
    cambiate = salva_stili(s, stili)
    s.commit()
    log.info("Stemmi e colori aggiornati per %s squadre", cambiate)
    return cambiate
