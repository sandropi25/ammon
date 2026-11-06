"""Passo del job notturno: biografie dei giocatori di Serie A e Liga (ESPN + Wikipedia).

Al più `BIO_PER_NOTTE` giocatori per notte (variabile d'ambiente, predefinito 40): prima
quelli di Serie A, poi quelli di Liga, i più ammoniti per primi. Un giocatore si ricontrolla
al più una volta al mese (`GIORNI_RINNOVO`), anche se l'ultima volta non si era trovato
nulla. Una voce di Wikipedia dubbia non si salva (resta quella eventualmente già salvata)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ammonizioni.config import CAMPIONATI, SERIE_A, STAGIONE_CORRENTE
from ammonizioni.db.modelli import Giocatore, Partita, Presenza
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.limite import LimiteSuperato

log = logging.getLogger(__name__)

GIORNI_RINNOVO = 30
BIO_PER_NOTTE = 40


def massimo_per_notte() -> int:
    valore = os.environ.get("BIO_PER_NOTTE", "").strip()
    try:
        return max(0, int(valore)) if valore else BIO_PER_NOTTE
    except ValueError:
        return BIO_PER_NOTTE


@dataclass
class RiepilogoBio:
    controllati: int = 0
    con_anagrafica: int = 0
    con_wikipedia: int = 0
    completo: bool = True


def da_aggiornare(
    s: Session, adesso: datetime, quanti: int, stagione: int = STAGIONE_CORRENTE
) -> list[int]:
    """Id dei giocatori con presenze nella stagione in Serie A o Liga, senza biografia o
    controllati più di un mese fa: Serie A per prima, poi i più ammoniti (una query)."""
    if quanti <= 0:
        return []
    soglia = adesso - timedelta(days=GIORNI_RINNOVO)
    righe = s.execute(
        select(
            Presenza.giocatore_id,
            Partita.competizione_id,
            func.sum(Presenza.gialli),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.stagione == stagione,
            or_(Giocatore.bio_aggiornata.is_(None), Giocatore.bio_aggiornata < soglia),
        )
        .group_by(Presenza.giocatore_id, Partita.competizione_id)
    ).all()
    # (in Serie A?, gialli) per giocatore; SUM su Postgres è Decimal: convertito in int
    voci: dict[int, tuple[bool, int]] = {}
    for gid, campionato, gialli in righe:
        serie_a, totale = voci.get(gid, (False, 0))
        voci[gid] = (serie_a or campionato == SERIE_A, totale + int(gialli or 0))
    ordine = sorted(voci, key=lambda g: (not voci[g][0], -voci[g][1], g))
    return ordine[:quanti]


def aggiorna(
    s: Session,
    client,
    adesso: datetime | None = None,
    quanti: int | None = None,
    usa_espn: bool = True,
) -> RiepilogoBio:
    """Cerca le biografie dei giocatori da aggiornare e le salva (commit per giocatore).
    `usa_espn=False` quando gli id del database non sono quelli ESPN (fonte API-Football):
    in quel caso solo Wikipedia. Se il budget ESPN finisce si ferma (completo=False)."""
    adesso = adesso or datetime.now(timezone.utc)
    quanti = massimo_per_notte() if quanti is None else quanti
    riepilogo = RiepilogoBio()
    for gid in da_aggiornare(s, adesso, quanti):
        giocatore = s.get(Giocatore, gid)
        anagrafica = None
        if usa_espn:
            try:
                anagrafica = client.anagrafica(gid)
            except LimiteSuperato:
                riepilogo.completo = False
                break
            except ErroreFonte as errore:
                log.warning("Anagrafica ESPN di %s non letta: %s", giocatore.nome, errore)
                riepilogo.completo = False
        anno = anagrafica.data_nascita.year if anagrafica and anagrafica.data_nascita else None
        try:
            profilo = client.profilo_wikipedia(giocatore.nome, anno)
        except ErroreFonte as errore:
            log.warning("Wikipedia per %s non letta: %s", giocatore.nome, errore)
            riepilogo.completo = False
            profilo = None
        if anagrafica is not None:
            riepilogo.con_anagrafica += 1
            for campo in ("data_nascita", "nazionalita", "altezza_cm", "posizione"):
                valore = getattr(anagrafica, campo)
                if valore is not None:
                    setattr(giocatore, campo, valore)
        if profilo is not None:
            riepilogo.con_wikipedia += 1
            giocatore.wiki_titolo = profilo.titolo
            giocatore.wiki_url = profilo.url
            giocatore.wiki_estratto = profilo.estratto
        giocatore.bio_aggiornata = adesso
        riepilogo.controllati += 1
        s.commit()
    return riepilogo
