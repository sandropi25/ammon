"""Storico graduale: poche richieste al giorno (priorità STORICO) per riempire le 3 stagioni,
partendo dalle squadre che giocano nei prossimi giorni."""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.caricamento import arbitri_fd
from ammonizioni.caricamento.notturno import (
    FonteContata,
    RiepilogoJob,
    salva_partita,
    scarica_statistiche_partita,
)
from ammonizioni.config import COMPETIZIONI, STAGIONE_CORRENTE, STAGIONI, STATI_FINITI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Partita
from ammonizioni.fonti.base import ErroreFonte, Fonte
from ammonizioni.fonti.limite import LimiteSuperato

log = logging.getLogger(__name__)

CALENDARI_SCARICATI = "calendari_scaricati"
CALENDARI_QUANDO = "calendari_scaricati_il"  # {"competizione-stagione": iso UTC}
GIORNI_PROSSIMA_GIORNATA = 7
GIORNI_RISCARICO_CALENDARIO = 7  # calendari della stagione corrente (non Serie A)
ARBITRI_COLLEGATI = "arbitri_collegati"  # stagioni di Serie A con gli arbitri gia' collegati
MINUTI_MASSIMI_STORICO = 40  # con ESPN (30 richieste/min) il primo carico dura piu' di 50 minuti


class TempoEsaurito(Exception):
    """Il tempo massimo di una esecuzione dello storico e' finito."""


# Competizioni caricate oggi: Liga e Copa del Rey entrano con il Task 5 (più campionati),
# finché non è fatto il comportamento resta quello della sola Serie A e coppe europee.
_COMPETIZIONI_CARICATE = tuple(
    v for k, v in COMPETIZIONI.items() if k not in ("liga", "copa_del_rey")
)


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
        for competizione_id in _COMPETIZIONI_CARICATE:
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
            Partita.stato.in_(STATI_FINITI),
            Partita.statistiche_scaricate.is_(False),
            Partita.competizione_id.in_(_COMPETIZIONI_CARICATE),
            Partita.stagione.in_(STAGIONI),
        )
        .order_by(Partita.data_utc.desc())
    ).all()
    prima = [p.id for p in partite if p.casa_id in squadre or p.trasferta_id in squadre]
    dopo = [p.id for p in partite if not (p.casa_id in squadre or p.trasferta_id in squadre)]
    return prima + dopo


def _scarica_calendari(s: Session, fonte: Fonte, oggi: datetime, verifica_tempo) -> None:
    for competizione_id, stagione in coda_storico(s, oggi):
        verifica_tempo()
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


def max_minuti_da_env() -> int:
    """Minuti massimi di una esecuzione di `avanza`: STORICO_MAX_MINUTI (default 40)."""
    valore = os.environ.get("STORICO_MAX_MINUTI", "").strip()
    return int(valore) if valore else MINUTI_MASSIMI_STORICO


def _collega_arbitri_stagioni(s: Session, fonte_fd) -> bool:
    """Arbitri della Serie A per ogni stagione dello storico, una volta sola per stagione
    (una richiesta a football-data.org per stagione: `collega` sull'intero intervallo
    1 luglio - 30 giugno). Vale anche per la stagione corrente: il job notturno collega solo
    le partite da 7 giorni fa a fra 7 giorni. Senza chiave non fa nulla (e non segna nulla).
    True se non ci sono stati errori."""
    if not getattr(fonte_fd, "chiave", None):
        return True
    fatte = set(repo.leggi_impostazione(s, ARBITRI_COLLEGATI, []) or [])
    completo = True
    for stagione in STAGIONI:  # dalla piu' recente
        if stagione in fatte:
            continue
        # calendario non ancora scaricato (o fallito): niente da collegare, si riprova
        if s.scalars(
            select(Partita.id)
            .where(Partita.competizione_id == COMPETIZIONI["serie_a"], Partita.stagione == stagione)
            .limit(1)
        ).first() is None:
            continue
        try:
            arbitri_fd.collega(
                s, fonte_fd, COMPETIZIONI["serie_a"], date(stagione, 7, 1), date(stagione + 1, 6, 30)
            )
        except (ErroreFonte, LimiteSuperato) as errore:
            s.rollback()
            log.warning("Arbitri Serie A %s non collegati: %s", stagione, errore)
            completo = False
            continue
        fatte.add(stagione)
        repo.scrivi_impostazione(s, ARBITRI_COLLEGATI, sorted(fatte, reverse=True))
        s.commit()
    return completo


def avanza(
    s: Session,
    fonte_storico: Fonte,
    fonte_fd=None,
    orologio=time.monotonic,
    max_minuti: int | None = None,
) -> RiepilogoJob:
    """Elenchi partite mancanti (una richiesta ciascuno), poi le statistiche nell'ordine di
    `prossime_da_scaricare`, finché il budget STORICO non finisce (completo=False)."""
    oggi = datetime.now(timezone.utc)
    fonte = FonteContata(fonte_storico)
    completo = True
    limite_secondi = (max_minuti if max_minuti is not None else max_minuti_da_env()) * 60
    inizio = orologio()

    def verifica_tempo() -> None:
        if orologio() - inizio >= limite_secondi:
            raise TempoEsaurito()

    try:
        _scarica_calendari(s, fonte, oggi, verifica_tempo)
        if fonte_fd is not None:
            completo = _collega_arbitri_stagioni(s, fonte_fd) and completo
        for partita_id in prossime_da_scaricare(s, oggi):
            verifica_tempo()
            scarica_statistiche_partita(s, fonte, partita_id)
    except LimiteSuperato:
        s.commit()
        completo = False
    except TempoEsaurito:
        s.commit()
        completo = False
        log.info(
            "Storico fermato dopo %s minuti (STORICO_MAX_MINUTI): il resto alla prossima notte",
            limite_secondi // 60,
        )
    repo.segna_aggiornamento(s, "storico", completo)
    s.commit()
    return RiepilogoJob(fonte.richieste, fonte.statistiche_ricevute, completo)
