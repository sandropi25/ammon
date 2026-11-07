"""Orchestratore orario: decide se c'e' qualcosa da fare e, se no, esce subito senza richieste.
Lancio (ogni ora, minuto 05): `python -m ammonizioni.scheduler.orchestratore`.

Tre casi, tutti con l'ora italiana:
1. Aggiornamento della giornata: se oggi ci sono partite di campionato e la prima inizia fra
   6 e 7 ore, e non e' gia' stato fatto oggi, aggiorna calendario, statistiche delle partite
   giocate, arbitri, probabili formazioni, biografie e storico (col suo tetto di tempo).
   Se un cron viene saltato o ritardato, l'aggiornamento si recupera nelle ore seguenti
   fino a 3 ore prima della prima partita.
2. Chiusura: partite finite da almeno 2 ore (fine stimata = inizio + 2 ore) e non ancora
   chiuse: statistiche ed esiti delle giocate.
3. Altrimenti niente (giorni senza partite compresi).

Lo stato e' in Impostazione: "giornata_aggiornata" (data italiana dell'ultimo aggiornamento
della giornata) e "partite_chiuse" (id delle partite gia' chiuse): nulla gira due volte."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni import config
from ammonizioni.caricamento import designazioni, notturno
from ammonizioni.config import CAMPIONATI, STATI_FINITI
from ammonizioni.db import repo
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Partita
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.controllo_espn import controlla_struttura
from ammonizioni.fonti.limite import LimiteSuperato, Priorita
from ammonizioni.giocate.registro import aggiorna_esiti
from ammonizioni.scheduler.comune import (
    ErroreConfigurazione,
    configura_log,
    crea_football_data,
    crea_fonte as crea_fonte_predefinita,
)
from ammonizioni.scheduler.notte import aggiorna_biografie, aggiorna_tutto
from ammonizioni.scheduler.pre_partita import STATI_ESCLUSI, crea_probabili

log = logging.getLogger(__name__)

FUSO = ZoneInfo("Europe/Rome")
ANTICIPO_MAX = timedelta(hours=7)  # l'aggiornamento della giornata inizia 7 ore prima...
FINE_RECUPERO = timedelta(hours=3)  # ...la finestra normale e' 7-6 ore prima; cron saltato:
#                                     si recupera fino a 3 ore prima della prima partita
DURATA_PARTITA = timedelta(hours=2)  # fine stimata dopo il calcio d'inizio
ATTESA_CHIUSURA = timedelta(hours=2)  # la chiusura parte 2 ore dopo la fine stimata
GIORNI_CHIUSURA = 7  # partite piu' vecchie restano allo storico
TENTATIVI_CHIUSURA_MAX = 6  # dopo tanti tentativi a vuoto la partita si chiude comunque
CHIAVE_GIORNATA = "giornata_aggiornata"
CHIAVE_CHIUSE = "partite_chiuse"
CHIAVE_TENTATIVI = "chiusura_tentativi"


@dataclass
class Decisione:
    giornata: date | None = None  # data italiana da aggiornare, None = niente
    chiusura: list[int] = field(default_factory=list)  # id delle partite da chiudere

    @property
    def niente(self) -> bool:
        return self.giornata is None and not self.chiusura


def _limiti_giorno(giorno: date) -> tuple[datetime, datetime]:
    """Inizio e fine (UTC) di un giorno italiano; corretto anche nei giorni del cambio d'ora."""
    inizio = datetime.combine(giorno, time.min, tzinfo=FUSO).astimezone(timezone.utc)
    fine = datetime.combine(giorno + timedelta(days=1), time.min, tzinfo=FUSO).astimezone(
        timezone.utc
    )
    return inizio, fine


def _in_utc(quando: datetime) -> datetime:
    if quando.tzinfo is None:
        return quando.replace(tzinfo=timezone.utc)
    return quando.astimezone(timezone.utc)


def partite_del_giorno(s: Session, giorno: date) -> list[Partita]:
    inizio, fine = _limiti_giorno(giorno)
    return list(
        s.scalars(
            select(Partita)
            .where(
                Partita.competizione_id.in_(CAMPIONATI),
                Partita.stato.not_in(STATI_ESCLUSI),
                Partita.data_utc >= inizio,
                Partita.data_utc < fine,
            )
            .order_by(Partita.data_utc, Partita.id)
        )
    )


def giornata_da_aggiornare(s: Session, adesso_utc: datetime) -> date | None:
    """La data italiana di oggi se e' ora di aggiornare la giornata, altrimenti None."""
    oggi = adesso_utc.astimezone(FUSO).date()
    if repo.leggi_impostazione(s, CHIAVE_GIORNATA, None) == oggi.isoformat():
        return None
    partite = partite_del_giorno(s, oggi)
    if not partite:
        return None
    mancano = _in_utc(partite[0].data_utc) - adesso_utc
    if FINE_RECUPERO < mancano <= ANTICIPO_MAX:
        return oggi
    return None


def partite_da_chiudere(s: Session, adesso_utc: datetime) -> list[int]:
    """Partite di campionato finite da almeno 2 ore (negli ultimi 7 giorni) non ancora chiuse."""
    chiuse = {int(i) for i in repo.leggi_impostazione(s, CHIAVE_CHIUSE, []) or []}
    limite = adesso_utc - DURATA_PARTITA - ATTESA_CHIUSURA
    ids = s.scalars(
        select(Partita.id)
        .where(
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.stato.not_in(STATI_ESCLUSI),
            Partita.data_utc <= limite,
            Partita.data_utc >= adesso_utc - timedelta(days=GIORNI_CHIUSURA),
        )
        .order_by(Partita.data_utc, Partita.id)
    ).all()
    return [int(i) for i in ids if int(i) not in chiuse]


def decidi(s: Session, adesso_utc: datetime) -> Decisione:
    return Decisione(giornata_da_aggiornare(s, adesso_utc), partite_da_chiudere(s, adesso_utc))


def probabili_della_giornata(s: Session, giorno: date) -> int:
    """Probabili formazioni (dall'ultimo XI, senza richieste) per le partite di oggi."""
    n = 0
    for partita in partite_del_giorno(s, giorno):
        if partita.stato_formazioni == "probabili" and crea_probabili(s, partita):
            n += 1
    return n


def chiudi_partite(s: Session, fonte, ids: list[int]) -> int:
    """Chiusura: calendario dei campionati coinvolti (porta lo stato a FT), statistiche delle
    partite finite, esiti delle giocate. Una partita e' chiusa quando ha le statistiche, e'
    stata rinviata/annullata o dopo TENTATIVI_CHIUSURA_MAX tentativi a vuoto: non gira due
    volte. Restituisce quante partite sono state chiuse."""
    contata = notturno.FonteContata(fonte)
    campionati = sorted(
        set(s.scalars(select(Partita.competizione_id).where(Partita.id.in_(ids)))),
        key=CAMPIONATI.index,
    )
    try:
        for campionato in campionati:
            try:
                notturno.aggiorna_calendario(s, contata, competizione_id=campionato)
            except ErroreFonte as errore:
                s.rollback()
                log.warning("Calendario %s non aggiornato: %s", campionato, errore)
        for partita_id in ids:
            partita = s.get(Partita, partita_id)
            if partita.stato in STATI_FINITI and not partita.statistiche_scaricate:
                notturno.scarica_statistiche_partita(s, contata, partita_id)
    except LimiteSuperato:
        s.commit()
        log.warning("Limite di richieste raggiunto: chiusura interrotta")
    aggiorna_esiti(s)
    chiuse = [int(i) for i in repo.leggi_impostazione(s, CHIAVE_CHIUSE, []) or []]
    tentativi = dict(repo.leggi_impostazione(s, CHIAVE_TENTATIVI, {}) or {})
    nuove = 0
    for partita_id in ids:
        partita = s.get(Partita, partita_id)
        n = int(tentativi.get(str(partita_id), 0)) + 1
        if (
            partita.statistiche_scaricate
            or partita.stato in STATI_ESCLUSI
            or n >= TENTATIVI_CHIUSURA_MAX
        ):
            if partita_id not in chiuse:
                chiuse.append(partita_id)
                nuove += 1
            tentativi.pop(str(partita_id), None)
        else:
            tentativi[str(partita_id)] = n
    repo.scrivi_impostazione(s, CHIAVE_CHIUSE, chiuse)
    repo.scrivi_impostazione(s, CHIAVE_TENTATIVI, tentativi)
    repo.segna_aggiornamento(s, "chiusura", True)
    s.commit()
    log.info("Chiusura: %s richieste, %s partite chiuse su %s", contata.richieste, nuove, len(ids))
    return nuove


def main(
    argv=None,
    crea_fonte=crea_fonte_predefinita,
    crea_fd=crea_football_data,
    controllo=controlla_struttura,
    biografie=None,
    orologio=lambda: datetime.now(timezone.utc),
) -> int:
    """`orologio()` restituisce l'ora attuale (con fuso): iniettabile nei test."""
    biografie = biografie or aggiorna_biografie
    configura_log()
    adesso = _in_utc(orologio())
    with modulo_sessione.apri() as s:
        decisione = decidi(s, adesso)
        if decisione.niente:
            log.info("Niente da fare alle %s UTC", adesso.strftime("%Y-%m-%d %H:%M"))
            return 0
        try:
            fonte_oggi = crea_fonte(s, Priorita.OGGI)
            fonte_storico = crea_fonte(s, Priorita.STORICO) if decisione.giornata else None
        except ErroreConfigurazione as errore:
            log.error("%s", errore)
            return 2
        espn = config.fonte_dati() == "espn"
        esito = 0
        if decisione.giornata is not None:
            fonte_fd = crea_fd(s) if espn else None
            try:
                if espn:  # arbitri designati dall'AIA, prima del collegamento football-data
                    designazioni.collega_designazioni_periodico(s, adesso)
                aggiorna_tutto(
                    s, fonte_oggi, fonte_storico, fonte_fd, controllo if espn else None,
                    biografie, adesso=adesso, etichetta="Giornata",
                )
                log.info(
                    "Probabili formazioni create per %s partite",
                    probabili_della_giornata(s, decisione.giornata),
                )
                repo.scrivi_impostazione(s, CHIAVE_GIORNATA, decisione.giornata.isoformat())
                s.commit()
            except Exception:  # noqa: BLE001 - riprova all'ora dopo (nessun segno di "fatto")
                s.rollback()
                log.exception("Aggiornamento della giornata non riuscito")
                esito = 1
            # ricalcolata: il calendario appena aggiornato puo' aver cambiato le partite
            decisione.chiusura = partite_da_chiudere(s, adesso)
        if decisione.chiusura:
            try:
                chiudi_partite(s, fonte_oggi, decisione.chiusura)
            except Exception:  # noqa: BLE001
                s.rollback()
                log.exception("Chiusura non riuscita")
                esito = 1
    return esito


if __name__ == "__main__":
    raise SystemExit(main())
