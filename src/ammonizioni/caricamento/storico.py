"""Storico graduale: poche richieste al giorno (priorità STORICO) per riempire le 3 stagioni,
partendo dalle squadre che giocano nei prossimi giorni."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.notturno import (
    FonteContata,
    RiepilogoJob,
    salva_partita,
    scarica_statistiche_partita,
)
from ammonizioni.config import COMPETIZIONI, STAGIONE_CORRENTE, STAGIONI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Partita
from ammonizioni.fonti.base import ErroreFonte, Fonte
from ammonizioni.fonti.limite import LimiteSuperato

log = logging.getLogger(__name__)

CALENDARI_SCARICATI = "calendari_scaricati"
CALENDARI_QUANDO = "calendari_scaricati_il"  # {"competizione-stagione": iso UTC}
GIORNI_PROSSIMA_GIORNATA = 7
GIORNI_RISCARICO_CALENDARIO = 7  # calendari della stagione corrente (non Serie A)


def _scaricati(s: Session) -> set[tuple[int, int]]:
    coppie = repo.leggi_impostazione(s, CALENDARI_SCARICATI, []) or []
    return {(c, st) for c, st in coppie}


def coda_storico(s: Session, oggi: datetime) -> list[tuple[int, int]]:
    """(competizione, stagione) di cui manca l'elenco partite, stagioni recenti per prime.
    Il calendario Serie A della stagione corrente è già aggiornato dal job notturno."""
    fatti = _scaricati(s)
    quando = repo.leggi_impostazione(s, CALENDARI_QUANDO, {}) or {}
    coda = []
    for stagione in STAGIONI:
        if stagione > oggi.year:
            continue
        for competizione_id in COMPETIZIONI.values():
            coppia = (competizione_id, stagione)
            if coppia == (COMPETIZIONI["serie_a"], STAGIONE_CORRENTE):
                continue
            if coppia in fatti and not (
                stagione == STAGIONE_CORRENTE
                and _scaduto(quando.get(_chiave(coppia)), oggi)
            ):
                continue
            coda.append(coppia)
    return coda


def _chiave(coppia: tuple[int, int]) -> str:
    return f"{coppia[0]}-{coppia[1]}"


def _scaduto(iso: str | None, oggi: datetime) -> bool:
    """True se il calendario della stagione corrente ha più di 7 giorni (o data ignota)."""
    if not iso:
        return True
    return oggi - datetime.fromisoformat(iso) > timedelta(days=GIORNI_RISCARICO_CALENDARIO)


def _squadre_prossima_giornata(s: Session, oggi: datetime) -> set[int]:
    righe = s.execute(
        select(Partita.casa_id, Partita.trasferta_id).where(
            Partita.competizione_id == COMPETIZIONI["serie_a"],
            Partita.data_utc >= oggi,
            Partita.data_utc < oggi + timedelta(days=GIORNI_PROSSIMA_GIORNATA),
            Partita.stato.in_(("NS", "TBD")),
        )
    ).all()
    return {squadra for riga in righe for squadra in riga}


def prossime_da_scaricare(s: Session, oggi: datetime) -> list[int]:
    """Id delle partite giocate senza statistiche: prima quelle di squadre che giocano nei
    prossimi 7 giorni, poi le altre; in ciascun gruppo dalla più recente."""
    squadre = _squadre_prossima_giornata(s, oggi)
    partite = s.execute(
        select(Partita.id, Partita.casa_id, Partita.trasferta_id)
        .where(
            Partita.stato == "FT",
            Partita.statistiche_scaricate.is_(False),
            Partita.competizione_id.in_(COMPETIZIONI.values()),
            Partita.stagione.in_(STAGIONI),
        )
        .order_by(Partita.data_utc.desc())
    ).all()
    prima = [p.id for p in partite if p.casa_id in squadre or p.trasferta_id in squadre]
    dopo = [p.id for p in partite if not (p.casa_id in squadre or p.trasferta_id in squadre)]
    return prima + dopo


def _scarica_calendari(s: Session, fonte: Fonte, oggi: datetime) -> None:
    for competizione_id, stagione in coda_storico(s, oggi):
        try:
            partite = fonte.partite(competizione_id, stagione)
        except ErroreFonte as errore:
            log.warning(
                "Calendario %s/%s non scaricato: %s", competizione_id, stagione, errore
            )
            continue
        for dati in partite:
            salva_partita(s, dati)
        fatti = repo.leggi_impostazione(s, CALENDARI_SCARICATI, []) or []
        if [competizione_id, stagione] not in fatti:
            repo.scrivi_impostazione(
                s, CALENDARI_SCARICATI, fatti + [[competizione_id, stagione]]
            )
        quando = dict(repo.leggi_impostazione(s, CALENDARI_QUANDO, {}) or {})
        quando[_chiave((competizione_id, stagione))] = oggi.isoformat()
        repo.scrivi_impostazione(s, CALENDARI_QUANDO, quando)
        s.commit()


def avanza(s: Session, fonte_storico: Fonte) -> RiepilogoJob:
    """Elenchi partite mancanti (una richiesta ciascuno), poi le statistiche nell'ordine di
    `prossime_da_scaricare`, finché il budget STORICO non finisce (completo=False)."""
    oggi = datetime.now(timezone.utc)
    fonte = FonteContata(fonte_storico)
    completo = True
    try:
        _scarica_calendari(s, fonte, oggi)
        for partita_id in prossime_da_scaricare(s, oggi):
            scarica_statistiche_partita(s, fonte, partita_id)
    except LimiteSuperato:
        s.commit()
        completo = False
    repo.segna_aggiornamento(s, "storico", completo)
    s.commit()
    return RiepilogoJob(fonte.richieste, fonte.statistiche_ricevute, completo)
