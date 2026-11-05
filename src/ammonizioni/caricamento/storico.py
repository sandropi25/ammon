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
from ammonizioni.config import (
    CAMPIONATI,
    COMPETIZIONI,
    NOMI_CAMPIONATI,
    SERIE_A,
    STAGIONE_CORRENTE,
    STAGIONI,
    STATI_FINITI,
    campionato_di,
)
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
ARBITRI_RICOLLEGATI_QUANDO = "arbitri_ricollegati_il"  # {"campionato": iso UTC}, stagione corrente
MINUTI_MASSIMI_STORICO = 40 # con ESPN (30 richieste/min) il primo carico dura piu' di 50 minuti


class TempoEsaurito(Exception):
    """Il tempo massimo di una esecuzione dello storico e' finito."""


def _rango_competizione(competizione_id: int) -> int:
    """Precedenza di una competizione nelle code: 0 per la Serie A, la Coppa Italia e le
    coppe europee (che hanno anche le squadre di Serie A), poi la Liga e la sua coppa."""
    campionato = campionato_di(competizione_id)
    return CAMPIONATI.index(campionato) if campionato is not None else 0


def _scaricati(s: Session) -> set[tuple[int, int]]:
    coppie = repo.leggi_impostazione(s, CALENDARI_SCARICATI, []) or []
    return {(c, st) for c, st in coppie}


def coda_storico(s: Session, oggi: datetime) -> list[tuple[int, int]]:
    """(competizione, stagione) di cui manca l'elenco partite: prima le competizioni della
    Serie A (Serie A, Coppa Italia, coppe europee), poi quelle della Liga; in ciascun gruppo
    le stagioni recenti per prime. I calendari dei campionati della stagione corrente sono
    già aggiornati dal job notturno."""
    fatti = _scaricati(s)
    quando = repo.leggi_impostazione(s, CALENDARI_QUANDO, {}) or {}
    coda = []
    for rango in range(len(CAMPIONATI)):
        for stagione in STAGIONI:
            if stagione > oggi.year:
                continue
            for competizione_id in COMPETIZIONI.values():
                if _rango_competizione(competizione_id) != rango:
                    continue
                coppia = (competizione_id, stagione)
                if competizione_id in CAMPIONATI and stagione == STAGIONE_CORRENTE:
                    continue  # lo scarica ogni notte il job notturno
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
    """Squadre dei campionati che giocano nei prossimi 7 giorni."""
    righe = s.execute(
        select(Partita.casa_id, Partita.trasferta_id).where(
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.data_utc >= oggi,
            Partita.data_utc < oggi + timedelta(days=GIORNI_PROSSIMA_GIORNATA),
            Partita.stato.in_(("NS", "TBD")),
        )
    ).all()
    return {squadra for riga in righe for squadra in riga}


def _squadre_per_campionato(s: Session) -> list[set[int]]:
    """Per ogni campionato (nell'ordine di `CAMPIONATI`) le squadre che vi hanno giocato."""
    risultato = []
    for campionato in CAMPIONATI:
        righe = s.execute(
            select(Partita.casa_id, Partita.trasferta_id)
            .where(Partita.competizione_id == campionato, Partita.stagione.in_(STAGIONI))
            .distinct()
        ).all()
        risultato.append({squadra for riga in righe for squadra in riga})
    return risultato


def prossime_da_scaricare(s: Session, oggi: datetime) -> list[int]:
    """Id delle partite giocate senza statistiche. Prima la Serie A: le sue partite, la Coppa
    Italia e le coppe europee con una squadra di Serie A; poi quelle della Liga (campionato,
    Copa del Rey, coppe europee con una squadra di Liga e nessuna di Serie A); in fondo le
    coppe europee tra altre squadre. In ciascun gruppo prima le partite di squadre che giocano
    nei prossimi 7 giorni, poi le altre; sempre dalla più recente."""
    squadre = _squadre_prossima_giornata(s, oggi)
    squadre_campionati = _squadre_per_campionato(s)
    partite = s.execute(
        select(Partita.id, Partita.casa_id, Partita.trasferta_id, Partita.competizione_id)
        .where(
            Partita.stato.in_(STATI_FINITI),
            Partita.statistiche_scaricate.is_(False),
            Partita.competizione_id.in_(COMPETIZIONI.values()),
            Partita.stagione.in_(STAGIONI),
        )
        .order_by(Partita.data_utc.desc())
    ).all()

    def rango(p) -> tuple[int, int]:
        campionato = campionato_di(p.competizione_id)
        if campionato is not None:
            gruppo = CAMPIONATI.index(campionato)
        else:  # coppa europea: il primo campionato di cui ha una squadra
            gruppo = next(
                (
                    i
                    for i, squadre_c in enumerate(squadre_campionati)
                    if p.casa_id in squadre_c or p.trasferta_id in squadre_c
                ),
                len(CAMPIONATI),
            )
        prossima = p.casa_id in squadre or p.trasferta_id in squadre
        return gruppo, 0 if prossima else 1

    return [p.id for p in sorted(partite, key=rango)]  # sort stabile: resta l'ordine per data


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
    if not valore:
        return MINUTI_MASSIMI_STORICO
    try:
        return int(valore)
    except ValueError:
        log.warning(
            "STORICO_MAX_MINUTI=%r non e' un numero: uso %s minuti", valore, MINUTI_MASSIMI_STORICO
        )
        return MINUTI_MASSIMI_STORICO


def _chiave_arbitri(campionato: int) -> str:
    """Impostazione con le stagioni già collegate: per la Serie A resta `arbitri_collegati`."""
    return ARBITRI_COLLEGATI if campionato == SERIE_A else f"{ARBITRI_COLLEGATI}_{campionato}"


def _collega_arbitri_stagioni(s: Session, fonte_fd, oggi: datetime) -> bool:
    """Arbitri di ogni campionato (la Serie A per prima) per ogni stagione dello storico, una
    volta sola per stagione (una richiesta a football-data.org per campionato e stagione:
    `collega` sull'intero intervallo 1 luglio - 30 giugno). Per la stagione corrente si
    ripete ogni 7 giorni (le partite ancora senza arbitro, che football-data ha designato
    dopo; senza partite senza arbitro `collega` non fa richieste): il job notturno collega
    solo le partite da 7 giorni fa a fra 7 giorni. Senza chiave non fa nulla (e non segna
    nulla). True se non ci sono stati errori."""
    if fonte_fd is not None and not getattr(fonte_fd, "chiave", None):
        log.warning(
            "Arbitri dello storico non collegati: manca la chiave football-data.org "
            "(FOOTBALL_DATA_KEY). Le partite restano senza arbitro finché non la imposti."
        )
        return True
    if fonte_fd is None:
        return True
    completo = True
    quando = dict(repo.leggi_impostazione(s, ARBITRI_RICOLLEGATI_QUANDO, {}) or {})
    for campionato in CAMPIONATI:
        chiave = _chiave_arbitri(campionato)
        fatte = set(repo.leggi_impostazione(s, chiave, []) or [])
        for stagione in STAGIONI:  # dalla piu' recente
            corrente = stagione == STAGIONE_CORRENTE
            if corrente:
                if not _scaduto(quando.get(str(campionato)), oggi):
                    continue
            elif stagione in fatte:
                continue
            # calendario non ancora scaricato (o fallito): niente da collegare, si riprova
            if s.scalars(
                select(Partita.id)
                .where(Partita.competizione_id == campionato, Partita.stagione == stagione)
                .limit(1)
            ).first() is None:
                continue
            try:
                arbitri_fd.collega(
                    s, fonte_fd, campionato, date(stagione, 7, 1), date(stagione + 1, 6, 30)
                )
            except (ErroreFonte, LimiteSuperato) as errore:
                s.rollback()
                log.warning(
                    "Arbitri %s %s non collegati: %s", NOMI_CAMPIONATI[campionato], stagione, errore
                )
                completo = False
                continue
            fatte.add(stagione)
            repo.scrivi_impostazione(s, chiave, sorted(fatte, reverse=True))
            if corrente:
                quando[str(campionato)] = oggi.isoformat()
                repo.scrivi_impostazione(s, ARBITRI_RICOLLEGATI_QUANDO, quando)
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
            completo = _collega_arbitri_stagioni(s, fonte_fd, oggi) and completo
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
