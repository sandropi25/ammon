"""Foto dei giocatori (TheSportsDB): chi cercare, in che ordine, cosa salvare.

Si cerca chi non è mai stato controllato, chi è stato controllato più di 30 giorni fa senza
trovare la foto e chi ha la foto da più di 90 giorni. Prima i giocatori delle prossime
partite (`priorita_ids`), poi quelli con la presenza più recente. Al più `limite` ricerche
per chiamata (una ogni 2,2 secondi: il limite gratuito è di 30 al minuto); si salva a piccoli
gruppi e con una risposta 429 ci si ferma tenendo quanto già fatto."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ammonizioni.config import CAMPIONATI
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti import foto as fonti_foto
from ammonizioni.fonti.foto import LimiteFoto, cerca_foto

log = logging.getLogger(__name__)

GIORNI_SENZA_FOTO = 30
GIORNI_CON_FOTO = 90
COMMIT_OGNI = 5


def da_cercare(
    s: Session,
    adesso: datetime,
    limite: int,
    priorita_ids: Iterable[int] = (),
    solo_ids: Iterable[int] | None = None,
) -> list[int]:
    """Id dei giocatori da cercare, nell'ordine: prima `priorita_ids`, poi la presenza più
    recente. `solo_ids` restringe la scelta a quei giocatori (None: tutti)."""
    if limite <= 0:
        return []
    senza = adesso - timedelta(days=GIORNI_SENZA_FOTO)
    con = adesso - timedelta(days=GIORNI_CON_FOTO)
    candidati = {
        int(g)
        for g in s.scalars(
            select(Giocatore.id).where(
                or_(
                    Giocatore.foto_controllata.is_(None),
                    (Giocatore.foto_url.is_(None)) & (Giocatore.foto_controllata < senza),
                    (Giocatore.foto_url.is_not(None)) & (Giocatore.foto_controllata < con),
                )
            )
        )
    }
    if solo_ids is not None:
        candidati &= {int(g) for g in solo_ids}
    if not candidati:
        return []
    ultima = {
        int(gid): quando
        for gid, quando in s.execute(
            select(Presenza.giocatore_id, func.max(Partita.data_utc))
            .join(Partita, Partita.id == Presenza.partita_id)
            .group_by(Presenza.giocatore_id)
        )
        if int(gid) in candidati
    }
    prioritari = {int(g) for g in priorita_ids}

    def chiave(gid: int):
        quando = ultima.get(gid)
        # data senza fuso (sqlite) o con fuso (Postgres): si confrontano come naive
        secondi = quando.replace(tzinfo=None).timestamp() if quando is not None else 0.0
        return (gid not in prioritari, -secondi, gid)

    return sorted(candidati, key=chiave)[:limite]


def giocatori_prossime_partite(s: Session, adesso: datetime, giorni: int = 2) -> list[int]:
    """Id dei giocatori nelle formazioni (ufficiali, panchina o probabili) delle partite di
    campionato dei prossimi `giorni` giorni (una query)."""
    return [
        int(g)
        for g in s.scalars(
            select(Formazione.giocatore_id)
            .join(Partita, Partita.id == Formazione.partita_id)
            .where(
                Partita.competizione_id.in_(CAMPIONATI),
                Partita.data_utc > adesso,
                Partita.data_utc <= adesso + timedelta(days=giorni),
            )
            .distinct()
        )
    ]


def aggiorna_foto_senza_errori(s: Session, adesso: datetime, limite: int, giorni: int = 2) -> int:
    """Passo dei job: foto prima dei giocatori delle prossime partite. Un errore, di qualsiasi
    tipo, è scritto nel log e non ferma il job. Restituisce i giocatori controllati."""
    try:
        priorita = giocatori_prossime_partite(s, adesso, giorni)
        client = fonti_foto.crea_client()
        try:
            n = aggiorna_foto(s, client, adesso, limite=limite, priorita_ids=priorita)
        finally:
            client.close()
        if n:
            log.info("Foto dei giocatori: %s controllati", n)
        return n
    except Exception:  # noqa: BLE001 - le foto non devono fermare il job
        s.rollback()
        log.exception("Foto dei giocatori non aggiornate")
        return 0


def _squadra_recente(s: Session, giocatore_id: int) -> str | None:
    return s.scalars(
        select(Squadra.nome)
        .join(Presenza, Presenza.squadra_id == Squadra.id)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(Presenza.giocatore_id == giocatore_id)
        .order_by(Partita.data_utc.desc())
        .limit(1)
    ).first()


def aggiorna_foto(
    s: Session,
    client,
    adesso: datetime,
    limite: int = 25,
    priorita_ids: Iterable[int] = (),
    solo_ids: Iterable[int] | None = None,
    avanzamento: Callable[[int, int, Giocatore], None] | None = None,
) -> int:
    """Cerca le foto di al più `limite` giocatori e le salva; restituisce quanti ne ha
    controllati (con o senza foto trovata). `avanzamento(fatti, totale, giocatore)` è
    chiamata dopo ogni giocatore (per gli script)."""
    ids = da_cercare(s, adesso, limite, priorita_ids, solo_ids)
    fatti = 0
    try:
        for gid in ids:
            giocatore = s.get(Giocatore, gid)
            if giocatore is None:
                continue
            url = cerca_foto(
                client, giocatore.nome, giocatore.data_nascita, _squadra_recente(s, gid)
            )
            if url is not None:
                giocatore.foto_url = url
            giocatore.foto_controllata = adesso
            fatti += 1
            if fatti % COMMIT_OGNI == 0:
                s.commit()
            if avanzamento is not None:
                avanzamento(fatti, len(ids), giocatore)
    except LimiteFoto:
        log.warning("TheSportsDB: limite di richieste raggiunto, foto interrotte")
    s.commit()
    return fatti
