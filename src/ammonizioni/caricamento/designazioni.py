"""Collega le designazioni ufficiali dell'AIA (Serie A) alle prossime partite del database:
l'arbitro e' noto 2-4 giorni prima, mentre football-data.org lo scrive solo a partita finita.
Il collegamento e' per squadre (casa con casa, trasferta con trasferta) tra le partite di
Serie A ancora da giocare; l'arbitro e' identificato dal cognome (`caricamento.arbitri`),
quindi "DI BELLO" e "Marco Di Bello" sono la stessa riga."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.arbitri import trova_o_crea
from ammonizioni.caricamento.arbitri_fd import nome_squadra_normalizzato
from ammonizioni.config import SERIE_A
from ammonizioni.db import repo
from ammonizioni.db.modelli import Partita, Squadra
from ammonizioni.fonti import designazioni as fonte

log = logging.getLogger(__name__)

CHIAVE_ULTIMO = "designazioni_ultimo"  # Impostazione: ultimo tentativo (ISO UTC)
INTERVALLO = timedelta(hours=3)
GIORNI_AVANTI = 21
STATI_ESCLUSI = ("PST", "CANC", "FT", "AET", "PEN")


def crea_client():
    """Client HTTP con User-Agent educato (sostituibile nei test)."""
    return fonte.crea_client()


def nome_arbitro(grezzo: str) -> str:
    """Nome dell'AIA ("SACCHI J.L.", "DI BELLO") nella forma da salvare ("Sacchi", "Di Bello"):
    senza iniziali puntate, con le maiuscole solo iniziali."""
    parole = [p for p in grezzo.split() if "." not in p]
    return " ".join(parole or grezzo.split()).title()


def collega_designazioni(
    s: Session, client, adesso_utc: datetime | None = None
) -> int:
    """Assegna l'arbitro designato dall'AIA alle partite di Serie A dei prossimi giorni.
    Riempie l'arbitro mancante e corregge quello diverso (una variazione di designazione);
    non scrive mai un arbitro vuoto e non tocca le partite gia' iniziate. Restituisce le
    partite modificate."""
    adesso = adesso_utc or datetime.now(timezone.utc)
    designazioni = fonte.designazioni_serie_a(client, oggi=adesso.date())
    if not designazioni:
        return 0
    partite = s.scalars(
        select(Partita)
        .where(
            Partita.competizione_id == SERIE_A,
            Partita.stato.not_in(STATI_ESCLUSI),
            Partita.data_utc > adesso,
            Partita.data_utc <= adesso + timedelta(days=GIORNI_AVANTI),
        )
        .order_by(Partita.data_utc, Partita.id)
    ).all()
    chiavi: dict[tuple[str, str], Partita] = {}
    for partita in partite:
        casa = s.get(Squadra, partita.casa_id)
        trasferta = s.get(Squadra, partita.trasferta_id)
        chiavi.setdefault(
            (nome_squadra_normalizzato(casa.nome), nome_squadra_normalizzato(trasferta.nome)),
            partita,  # la prima in ordine di data: la coppia c'e' una volta a stagione
        )
    modificate = 0
    for d in designazioni:
        partita = chiavi.get(
            (nome_squadra_normalizzato(d.casa), nome_squadra_normalizzato(d.trasferta))
        )
        if partita is None:
            log.info("Designazione %s - %s (%s): nessuna partita di Serie A da giocare",
                     d.casa, d.trasferta, d.arbitro)
            continue
        arbitro = trova_o_crea(s, nome_arbitro(d.arbitro), SERIE_A)
        if arbitro is None or partita.arbitro_id == arbitro.id:
            continue
        partita.arbitro_id = arbitro.id
        modificate += 1
    s.commit()
    return modificate


def _ultimo_tentativo(s: Session) -> datetime | None:
    valore = repo.leggi_impostazione(s, CHIAVE_ULTIMO, None)
    if not isinstance(valore, str):
        return None
    try:
        quando = datetime.fromisoformat(valore)
    except ValueError:
        return None
    return quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)


def collega_designazioni_periodico(
    s: Session, adesso_utc: datetime, client=None
) -> int:
    """Come `collega_designazioni`, ma al massimo ogni 3 ore (momento dell'ultimo tentativo
    in Impostazione). Non solleva mai: un errore e' scritto nel log. Restituisce le partite
    modificate."""
    ultimo = _ultimo_tentativo(s)
    if ultimo is not None and timedelta(0) <= adesso_utc - ultimo < INTERVALLO:
        return 0
    try:
        proprio = client is None
        client = client or crea_client()
        try:
            n = collega_designazioni(s, client, adesso_utc)
        finally:
            if proprio:
                client.close()
    except Exception:  # noqa: BLE001 - le designazioni non fermano il job
        s.rollback()
        log.warning("Designazioni AIA non collegate", exc_info=True)
        n = 0
    repo.scrivi_impostazione(s, CHIAVE_ULTIMO, adesso_utc.isoformat())
    s.commit()
    if n:
        log.info("Arbitri designati dall'AIA collegati: %s", n)
    return n
