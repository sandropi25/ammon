"""Controllo pre-partita: da 75 minuti prima del calcio d'inizio cerca le formazioni ufficiali.
Pensato per essere lanciato ogni 10 minuti: `python -m ammonizioni.scheduler.pre_partita`."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ammonizioni import config
from ammonizioni.caricamento.formazioni import salva_probabili, ultimo_xi
from ammonizioni.config import COMPETIZIONI
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Formazione, Giocatore, Partita
from ammonizioni.fonti.base import ErroreFonte, Fonte
from ammonizioni.fonti.limite import LimiteSuperato, Priorita
from ammonizioni.scheduler.comune import configura_log, crea_api_football, crea_limite

log = logging.getLogger(__name__)

MINUTI_FINESTRA = 75
STATI_ESCLUSI = ("PST", "CANC")


def partite_da_controllare(s: Session, adesso_utc: datetime) -> list[Partita]:
    """Serie A con formazioni ancora probabili, non rinviate/annullate, che iniziano entro 75 minuti."""
    return list(
        s.scalars(
            select(Partita)
            .where(
                Partita.competizione_id == COMPETIZIONI["serie_a"],
                Partita.stato_formazioni == "probabili",
                Partita.stato.not_in(STATI_ESCLUSI),
                Partita.data_utc > adesso_utc,
                Partita.data_utc <= adesso_utc + timedelta(minutes=MINUTI_FINESTRA),
            )
            .order_by(Partita.data_utc, Partita.id)
        )
    )


def _ha_probabili(s: Session, partita_id: int) -> bool:
    return (
        s.scalars(
            select(Formazione.giocatore_id)
            .where(Formazione.partita_id == partita_id, Formazione.tipo == "probabile")
            .limit(1)
        ).first()
        is not None
    )


def _complete(partita: Partita, formazioni) -> bool:
    """True se sono arrivati i titolari (non vuoti) di entrambe le squadre."""
    con_titolari = {f.squadra_id for f in formazioni if f.titolari}
    return {partita.casa_id, partita.trasferta_id} <= con_titolari


def _salva_ufficiali(s: Session, partita: Partita, formazioni) -> bool:
    """Salva le formazioni arrivate; la partita passa a "ufficiali" solo se sono complete
    (altrimenti resta "probabili" e il controllo successivo riprova). True se complete."""
    s.execute(
        delete(Formazione).where(
            Formazione.partita_id == partita.id, Formazione.tipo == "ufficiale"
        )
    )
    for formazione in formazioni:
        for giocatore_id, nome, ruolo, griglia in formazione.titolari:
            giocatore = s.get(Giocatore, giocatore_id)
            if giocatore is None:
                s.add(Giocatore(id=giocatore_id, nome=nome, ruolo=ruolo))
            elif giocatore.ruolo is None and ruolo is not None:
                giocatore.ruolo = ruolo
            s.add(
                Formazione(
                    partita_id=partita.id,
                    squadra_id=formazione.squadra_id,
                    giocatore_id=giocatore_id,
                    tipo="ufficiale",
                    griglia=griglia,
                )
            )
    if not _complete(partita, formazioni):
        return False
    partita.stato_formazioni = "ufficiali"
    return True


def esegui(s: Session, fonte: Fonte, adesso_utc: datetime) -> int:
    """Per ogni partita nella finestra: probabili dall'ultimo XI se mancano, poi cerca le
    ufficiali. Restituisce quante partite sono passate a "ufficiali"."""
    diventate_ufficiali = 0
    for partita in partite_da_controllare(s, adesso_utc):
        partita_id = partita.id
        try:
            if not _ha_probabili(s, partita_id):
                xi = {
                    squadra: ultimo_xi(s, squadra, partita.data_utc)
                    for squadra in (partita.casa_id, partita.trasferta_id)
                }
                salva_probabili(
                    s,
                    partita_id,
                    {squadra: [t.giocatore_id for t in titolari] for squadra, titolari in xi.items()},
                    griglie={t.giocatore_id: t.griglia for titolari in xi.values() for t in titolari},
                )
                s.commit()
            formazioni = fonte.formazioni(partita_id)
        except LimiteSuperato:
            s.commit()
            log.warning("Limite di richieste raggiunto: controllo formazioni interrotto")
            break
        except ErroreFonte as errore:
            log.warning("Formazioni della partita %s non lette: %s", partita_id, errore)
            continue
        if not formazioni:
            continue
        complete = _salva_ufficiali(s, partita, formazioni)
        s.commit()
        if complete:
            diventate_ufficiali += 1
        else:
            log.info("Formazioni della partita %s incomplete: riprovo", partita_id)
    return diventate_ufficiali


def main(argv=None, crea_fonte=crea_api_football) -> int:
    configura_log()
    with modulo_sessione.apri() as s:
        chiave = config.chiave_api(s)
        if not chiave:
            log.error("Chiave API-Football mancante (API_FOOTBALL_KEY o impostazione 'chiave_api')")
            return 2
        adesso = datetime.now(timezone.utc)
        if not partite_da_controllare(s, adesso):
            log.info("Nessuna partita nella finestra di controllo")
            return 0
        n = esegui(s, crea_fonte(chiave, Priorita.OGGI, crea_limite(s)), adesso)
        log.info("Formazioni ufficiali trovate per %s partite", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
