"""Job notturno: calendario Serie A, statistiche delle partite giocate, esiti delle giocate."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.arbitri import trova_o_crea
from ammonizioni.config import COMPETIZIONI, STAGIONE_CORRENTE, STATI_FINITI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti.base import ErroreFonte, Fonte
from ammonizioni.fonti.limite import LimiteSuperato
from ammonizioni.fonti.tipi import PartitaDati, PresenzaDati
from ammonizioni.giocate.registro import aggiorna_esiti

log = logging.getLogger(__name__)

GIORNI_STATISTICHE_NOTTE = 7


@dataclass
class RiepilogoJob:
    richieste_usate: int
    partite_aggiornate: int  # partite di cui sono state scaricate le statistiche
    completo: bool


class FonteContata:
    """Avvolge una Fonte e conta le richieste fatte (anche quelle finite in errore, non
    quelle bloccate da LimiteSuperato, che non consumano budget) e le statistiche ricevute
    (solo le risposte non vuote)."""

    def __init__(self, fonte: Fonte):
        self._fonte = fonte
        self.richieste = 0
        self.statistiche_ricevute = 0

    def _chiama(self, metodo: str, *argomenti):
        try:
            risultato = getattr(self._fonte, metodo)(*argomenti)
        except LimiteSuperato:
            raise
        except Exception:
            self.richieste += 1
            raise
        self.richieste += 1
        return risultato

    def partite(self, competizione_id, stagione):
        return self._chiama("partite", competizione_id, stagione)

    def partita(self, id):
        return self._chiama("partita", id)

    def statistiche(self, partita_id):
        risultato = self._chiama("statistiche", partita_id)
        if risultato:
            self.statistiche_ricevute += 1
        return risultato

    def formazioni(self, partita_id):
        return self._chiama("formazioni", partita_id)

def salva_partita(s: Session, dati: PartitaDati) -> Partita:
    """Crea o aggiorna squadre, arbitro e partita (senza toccare `statistiche_scaricate`)."""
    repo.upsert(s, Squadra(id=dati.casa_id, nome=dati.casa_nome))
    repo.upsert(s, Squadra(id=dati.trasferta_id, nome=dati.trasferta_nome))
    s.flush()
    arbitro = trova_o_crea(s, dati.arbitro_nome)
    partita = s.get(Partita, dati.id)
    if partita is None:
        partita = Partita(id=dati.id, statistiche_scaricate=False)
        s.add(partita)
    partita.data_utc = dati.data_utc
    partita.competizione_id = dati.competizione_id
    partita.stagione = dati.stagione
    partita.giornata = dati.giornata
    partita.casa_id = dati.casa_id
    partita.trasferta_id = dati.trasferta_id
    if arbitro is not None:
        partita.arbitro_id = arbitro.id
    partita.gol_casa = dati.gol_casa
    partita.gol_trasferta = dati.gol_trasferta
    partita.stato = dati.stato
    s.flush()
    return partita


def _salva_presenza(s: Session, dati: PresenzaDati) -> None:
    giocatore = {"id": dati.giocatore_id, "nome": dati.giocatore_nome}
    if dati.ruolo is not None:
        giocatore["ruolo"] = dati.ruolo
    repo.upsert(s, Giocatore(**giocatore))
    s.flush()
    repo.upsert(
        s,
        Presenza(
            partita_id=dati.partita_id,
            giocatore_id=dati.giocatore_id,
            squadra_id=dati.squadra_id,
            titolare=dati.titolare,
            ruolo=dati.ruolo,
            griglia=dati.griglia,
            minuti=dati.minuti,
            gialli=dati.gialli,
            rossi=dati.rossi,
            falli_commessi=dati.falli_commessi,
            falli_subiti=dati.falli_subiti,
            dribbling_tentati=dati.dribbling_tentati,
            dribbling_riusciti=dati.dribbling_riusciti,
            tiri=dati.tiri,
            gol=dati.gol,
            assist=dati.assist,
            voto=dati.voto,
        ),
    )


def scarica_statistiche_partita(s: Session, fonte: Fonte, partita_id: int) -> bool:
    """Scarica e salva le statistiche di una partita (commit incluso). Un ErroreFonte o una
    risposta vuota vengono registrati nel log e la partita saltata (False, resta da
    scaricare e verrà richiesta di nuovo); LimiteSuperato risale."""
    try:
        presenze = fonte.statistiche(partita_id)
    except ErroreFonte as errore:
        log.warning("Statistiche della partita %s non scaricate: %s", partita_id, errore)
        return False
    if not presenze:
        log.warning("Statistiche della partita %s vuote: riprovo la prossima volta", partita_id)
        return False
    for dati in presenze:
        _salva_presenza(s, dati)
    s.get(Partita, partita_id).statistiche_scaricate = True
    s.commit()
    return True


def aggiorna_calendario(s: Session, fonte: Fonte, stagione: int = STAGIONE_CORRENTE) -> int:
    """Partite Serie A della stagione (1 richiesta). Restituisce quante ne ha salvate."""
    partite = fonte.partite(COMPETIZIONI["serie_a"], stagione)
    for dati in partite:
        salva_partita(s, dati)
    s.commit()
    return len(partite)


def scarica_statistiche_giocate(s: Session, fonte: Fonte, adesso: datetime) -> int:
    """Statistiche delle partite di Serie A della stagione corrente finite negli ultimi
    7 giorni e non ancora scaricate, dalla più recente. Il resto (coppe, stagioni passate,
    partite più vecchie) resta allo storico, con priorità STORICO: il job notturno non
    deve consumare il budget del giorno (spec §3.3).
    Restituisce quante ne ha scaricate; su LimiteSuperato il lavoro già fatto resta salvato."""
    ids = s.scalars(
        select(Partita.id)
        .where(
            Partita.competizione_id == COMPETIZIONI["serie_a"],
            Partita.stagione == STAGIONE_CORRENTE,
            Partita.data_utc >= adesso - timedelta(days=GIORNI_STATISTICHE_NOTTE),
            Partita.stato.in_(STATI_FINITI),
            Partita.statistiche_scaricate.is_(False),
        )
        .order_by(Partita.data_utc.desc())
    ).all()
    scaricate = 0
    for partita_id in ids:
        if scarica_statistiche_partita(s, fonte, partita_id):
            scaricate += 1
    return scaricate


def esegui(s: Session, fonte: Fonte, adesso: datetime | None = None) -> RiepilogoJob:
    """Calendario, statistiche, esiti delle giocate; poi segna l'aggiornamento "notte".
    Se il limite di richieste finisce a metà, salva il parziale e restituisce completo=False.
    Un ErroreFonte sul calendario viene registrato nel log: statistiche ed esiti proseguono
    con le partite già note e l'aggiornamento risulta incompleto."""
    adesso = adesso or datetime.now(timezone.utc)
    contata = FonteContata(fonte)
    completo = True
    try:
        try:
            aggiorna_calendario(s, contata)
        except ErroreFonte as errore:
            log.warning("Calendario Serie A non aggiornato: %s", errore)
            completo = False
        scarica_statistiche_giocate(s, contata, adesso)
    except LimiteSuperato:
        s.commit()
        completo = False
    aggiorna_esiti(s)
    repo.segna_aggiornamento(s, "notte", completo)
    s.commit()
    return RiepilogoJob(contata.richieste, contata.statistiche_ricevute, completo)
