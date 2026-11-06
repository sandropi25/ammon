"""Controllo pre-partita: da 75 minuti prima del calcio d'inizio cerca le formazioni ufficiali.
Pensato per essere lanciato ogni 10 minuti: `python -m ammonizioni.scheduler.pre_partita`."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ammonizioni import config
from ammonizioni.caricamento import arbitri_fd
from ammonizioni.caricamento.formazioni import (
    probabili_automatiche,
    salva_probabili,
    ultimo_xi,
)
from ammonizioni.caricamento.notturno import indica_competizione
from ammonizioni.caricamento.stemmi import salva_stili_fonte
from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI, SERIE_A
from ammonizioni.db import repo
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Formazione, Giocatore, Partita
from ammonizioni.fonti.base import ErroreFonte, Fonte
from ammonizioni.fonti.limite import LimiteSuperato, Priorita
from ammonizioni.scheduler.comune import (
    ErroreConfigurazione,
    configura_log,
    crea_football_data,
    crea_fonte as crea_fonte_predefinita,
)

log = logging.getLogger(__name__)

MINUTI_FINESTRA = 75
STATI_ESCLUSI = ("PST", "CANC")
CHIAVE_ARBITRI_PROSSIMI = "arbitri_prossimi_ultimo"  # Impostazione: ultimo tentativo (ISO UTC)
INTERVALLO_ARBITRI = timedelta(hours=3)
GIORNI_ARBITRI = 7


def partite_da_controllare(s: Session, adesso_utc: datetime) -> list[Partita]:
    """Partite dei campionati (Serie A e Liga) con formazioni ancora probabili, non
    rinviate/annullate, che iniziano entro 75 minuti."""
    return list(
        s.scalars(
            select(Partita)
            .where(
                Partita.competizione_id.in_(CAMPIONATI),
                Partita.stato_formazioni == "probabili",
                Partita.stato.not_in(STATI_ESCLUSI),
                Partita.data_utc > adesso_utc,
                Partita.data_utc <= adesso_utc + timedelta(minutes=MINUTI_FINESTRA),
            )
            # la Serie A per prima: se il limite di richieste finisce, le sue partite sono servite
            .order_by(Partita.competizione_id != SERIE_A, Partita.data_utc, Partita.id)
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
            Formazione.partita_id == partita.id, Formazione.tipo.in_(("ufficiale", "panchina"))
        )
    )
    for formazione in formazioni:
        titolari = [(g, n, r, gr, "ufficiale") for g, n, r, gr in formazione.titolari]
        xi = {g for g, *_ in titolari}
        maglie = getattr(formazione, "maglie", None)
        maglie = maglie if isinstance(maglie, dict) else {}
        # la panchina in distinta (tipo "panchina"): i probabili subentranti
        panchina = [
            (g, n, r, None, "panchina")
            for g, n, r in formazione.panchina
            if g not in xi
        ]
        for giocatore_id, nome, ruolo, griglia, tipo in titolari + panchina:
            giocatore = s.get(Giocatore, giocatore_id)
            if giocatore is None:
                s.add(Giocatore(id=giocatore_id, nome=nome, ruolo=ruolo))
                s.flush()
            elif giocatore.ruolo is None and ruolo is not None:
                giocatore.ruolo = ruolo
            s.add(
                Formazione(
                    partita_id=partita.id,
                    squadra_id=formazione.squadra_id,
                    giocatore_id=giocatore_id,
                    tipo=tipo,
                    griglia=griglia,
                    maglia=maglie.get(giocatore_id),
                )
            )
    if not _complete(partita, formazioni):
        return False
    partita.stato_formazioni = "ufficiali"
    return True


def _salva_quote(s: Session, partita: Partita, fonte) -> None:
    """Probabilità implicite 1X2 prima della partita, se la fonte le ha lette (ESPN: stesso
    summary delle formazioni). Per ora solo salvate."""
    leggi = getattr(fonte, "quote_1x2", None)
    quote = leggi(partita.id) if callable(leggi) else None
    if quote:
        partita.prob_casa, partita.prob_pareggio, partita.prob_trasferta = quote


def esegui(s: Session, fonte: Fonte, adesso_utc: datetime) -> int:
    """Per ogni partita nella finestra: probabili dall'ultimo XI se mancano, poi cerca le
    ufficiali. Restituisce quante partite sono passate a "ufficiali"."""
    diventate_ufficiali = 0
    for partita in partite_da_controllare(s, adesso_utc):
        partita_id = partita.id
        try:
            if not _ha_probabili(s, partita_id):
                xi = {
                    squadra: probabili_automatiche(s, squadra, partita.data_utc)
                    or ultimo_xi(s, squadra, partita.data_utc)
                    for squadra in (partita.casa_id, partita.trasferta_id)
                }
                salva_probabili(
                    s,
                    partita_id,
                    {squadra: [t.giocatore_id for t in titolari] for squadra, titolari in xi.items()},
                    griglie={t.giocatore_id: t.griglia for titolari in xi.values() for t in titolari},
                )
                s.commit()
            indica_competizione(fonte, partita_id, partita.competizione_id)
            formazioni = fonte.formazioni(partita_id)
        except LimiteSuperato:
            s.commit()
            log.warning("Limite di richieste raggiunto: controllo formazioni interrotto")
            break
        except ErroreFonte as errore:
            log.warning("Formazioni della partita %s non lette: %s", partita_id, errore)
            continue
        _salva_quote(s, partita, fonte)
        salva_stili_fonte(s, fonte)  # stemmi e colori dallo stesso summary
        if not formazioni:
            continue
        complete = _salva_ufficiali(s, partita, formazioni)
        s.commit()
        if complete:
            diventate_ufficiali += 1
        else:
            log.info("Formazioni della partita %s incomplete: riprovo", partita_id)
    return diventate_ufficiali


def _ultimo_collegamento(s: Session) -> datetime | None:
    valore = repo.leggi_impostazione(s, CHIAVE_ARBITRI_PROSSIMI, None)
    if not isinstance(valore, str):
        return None
    try:
        quando = datetime.fromisoformat(valore)
    except ValueError:
        return None
    return quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)


def collega_arbitri_prossimi(s: Session, fonte_fd, adesso_utc: datetime) -> int:
    """Collega gli arbitri delle partite di campionato dei prossimi 7 giorni ancora senza
    arbitro (football-data.org li designa pochi giorni prima), al massimo ogni 3 ore (momento
    dell'ultimo tentativo in Impostazione): una richiesta per campionato che ha partite senza
    arbitro, nessuna altrimenti. Un errore della fonte e' scritto nel log e non ferma il job.
    Restituisce gli arbitri collegati."""
    if fonte_fd is None or not getattr(fonte_fd, "chiave", None):
        return 0
    ultimo = _ultimo_collegamento(s)
    if ultimo is not None and adesso_utc - ultimo < INTERVALLO_ARBITRI:
        return 0
    fine = adesso_utc + timedelta(days=GIORNI_ARBITRI)
    collegati = 0
    tentato = False
    for campionato in CAMPIONATI:
        senza_arbitro = s.scalars(
            select(Partita.id)
            .where(
                Partita.competizione_id == campionato,
                Partita.arbitro_id.is_(None),
                Partita.stato.not_in(STATI_ESCLUSI),
                Partita.data_utc > adesso_utc,
                Partita.data_utc <= fine,
            )
            .limit(1)
        ).first()
        if senza_arbitro is None:
            continue
        tentato = True
        try:
            collegati += arbitri_fd.collega(
                s, fonte_fd, campionato, adesso_utc.date(), fine.date()
            )
        except (ErroreFonte, LimiteSuperato) as errore:
            s.rollback()
            log.warning("Arbitri %s non collegati: %s", NOMI_CAMPIONATI[campionato], errore)
    if tentato:
        repo.scrivi_impostazione(s, CHIAVE_ARBITRI_PROSSIMI, adesso_utc.isoformat())
        s.commit()
    return collegati


def main(
    argv=None, crea_fonte=crea_fonte_predefinita, crea_fd=crea_football_data
) -> int:
    configura_log()
    with modulo_sessione.apri() as s:
        try:
            fonte = crea_fonte(s, Priorita.OGGI)
        except ErroreConfigurazione as errore:
            log.error("%s", errore)
            return 2
        adesso = datetime.now(timezone.utc)
        if config.fonte_dati() == "espn":  # con API-Football l'arbitro arriva dalla fonte
            n_arbitri = collega_arbitri_prossimi(s, crea_fd(s), adesso)
            if n_arbitri:
                log.info("Arbitri collegati alle prossime partite: %s", n_arbitri)
        if not partite_da_controllare(s, adesso):
            log.info("Nessuna partita nella finestra di controllo")
            return 0
        n = esegui(s, fonte, adesso)
        log.info("Formazioni ufficiali trovate per %s partite", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
