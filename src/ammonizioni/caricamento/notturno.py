"""Job notturno: calendario dei campionati (Serie A per prima), statistiche delle partite
giocate, arbitri ed esiti delle giocate."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni import config
from ammonizioni.caricamento import arbitri_fd
from ammonizioni.caricamento.arbitri import trova_o_crea
from ammonizioni.caricamento.stemmi import campi_stile, salva_stili_fonte
from ammonizioni.config import (
    CAMPIONATI,
    NOMI_CAMPIONATI,
    SERIE_A,
    STAGIONE_CORRENTE,
    STATI_FINITI,
    campionato_di,
)
from ammonizioni.db import repo
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti.base import ErroreFonte, Fonte
from ammonizioni.fonti.limite import LimiteSuperato
from ammonizioni.fonti.tipi import PartitaDati, PresenzaDati
from ammonizioni.giocate.registro import aggiorna_esiti

log = logging.getLogger(__name__)

GIORNI_STATISTICHE_NOTTE = 7
TENTATIVI_VUOTI = "statistiche_vuote_tentativi"  # {partita_id: risposte vuote ricevute}
TENTATIVI_VUOTI_MAX = 3  # dopo tanti tentativi vuoti una partita non-Serie A non si richiede piu'
GIORNI_ARBITRI = 7 # arbitri collegati per le partite da 7 giorni fa a fra 7 giorni


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

    def stili_squadre(self):
        """Stemmi e colori già letti dalla fonte (nessuna richiesta, non conta)."""
        leggi = getattr(self._fonte, "stili_squadre", None)
        return leggi() if callable(leggi) else {}

    def indica_competizione(self, partita_id, competizione_id):
        """Passa alla fonte (se lo sa usare) la competizione di una partita; non è una richiesta."""
        indica_competizione(self._fonte, partita_id, competizione_id)


def indica_competizione(fonte, partita_id: int, competizione_id: int) -> None:
    """Dice alla fonte a quale competizione appartiene la partita, se la fonte lo vuole sapere
    (ESPN ha un indirizzo per competizione e, in un processo nuovo, non conosce quelle già nel
    database: senza questo chiederebbe ogni partita alla Serie A)."""
    metodo = getattr(fonte, "indica_competizione", None)
    if metodo is not None:
        metodo(partita_id, competizione_id)

def salva_partita(s: Session, dati: PartitaDati) -> Partita:
    """Crea o aggiorna squadre, arbitro e partita (senza toccare `statistiche_scaricate`)."""
    # stemma e colori solo se la fonte li dà: un dato mancante non cancella quello salvato
    repo.upsert(s, Squadra(id=dati.casa_id, nome=dati.casa_nome, **campi_stile(dati.casa_stile)))
    repo.upsert(
        s,
        Squadra(id=dati.trasferta_id, nome=dati.trasferta_nome, **campi_stile(dati.trasferta_stile)),
    )
    s.flush()
    arbitro = trova_o_crea(s, dati.arbitro_nome, campionato_di(dati.competizione_id))
    partita = s.get(Partita, dati.id)
    if partita is None:
        partita = Partita(id=dati.id, statistiche_scaricate=False)
        s.add(partita)
    partita.data_utc = dati.data_utc
    partita.competizione_id = dati.competizione_id
    partita.stagione = dati.stagione
    if dati.giornata is not None:  # la giornata di football-data non va persa se la fonte non la da'
        partita.giornata = dati.giornata
    partita.casa_id = dati.casa_id
    partita.trasferta_id = dati.trasferta_id
    if arbitro is not None:
        partita.arbitro_id = arbitro.id
    partita.gol_casa = dati.gol_casa
    partita.gol_trasferta = dati.gol_trasferta
    partita.stato = dati.stato
    # totali dal tabellone solo se non ci sono le statistiche dei giocatori (che sono
    # complete e hanno la precedenza); un dato assente non cancella quello salvato
    if not partita.statistiche_scaricate:
        for campo in ("gialli_totali", "rossi_totali", "falli_totali"):
            valore = getattr(dati, campo)
            if valore is not None:
                setattr(partita, campo, valore)
    s.flush()
    return partita


def _griglia(s: Session, dati: PresenzaDati) -> str | None:
    """Griglia della presenza: quella ricevuta, altrimenti quella della formazione ufficiale
    salvata dal pre-partita, altrimenti quella già salvata (mai sovrascritta con None).
    /fixtures/players non la fornisce: arriva solo dalle formazioni."""
    if dati.griglia is not None:
        return dati.griglia
    ufficiale = s.get(
        Formazione, (dati.partita_id, dati.squadra_id, dati.giocatore_id, "ufficiale")
    )
    if ufficiale is not None and ufficiale.griglia is not None:
        return ufficiale.griglia
    esistente = s.get(Presenza, (dati.partita_id, dati.giocatore_id))
    return esistente.griglia if esistente is not None else None


def _salva_presenza(s: Session, dati: PresenzaDati) -> None:
    giocatore = {
        "id": dati.giocatore_id,
        "nome": config.nome_corretto(dati.giocatore_id, dati.giocatore_nome),
    }
    if dati.ruolo is not None:
        giocatore["ruolo"] = dati.ruolo
    repo.upsert(s, Giocatore(**giocatore))
    s.flush()
    griglia = _griglia(s, dati)
    # il numero di maglia solo se noto: una fonte senza numero non cancella quello salvato
    maglia = {"maglia": dati.maglia} if dati.maglia is not None else {}
    repo.upsert(
        s,
        Presenza(
            **maglia,
            partita_id=dati.partita_id,
            giocatore_id=dati.giocatore_id,
            squadra_id=dati.squadra_id,
            titolare=dati.titolare,
            ruolo=dati.ruolo,
            griglia=griglia,
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
    partita = s.get(Partita, partita_id)
    indica_competizione(fonte, partita_id, partita.competizione_id)
    try:
        presenze = fonte.statistiche(partita_id)
    except ErroreFonte as errore:
        log.warning("Statistiche della partita %s non scaricate: %s", partita_id, errore)
        return False
    tentativi = dict(repo.leggi_impostazione(s, TENTATIVI_VUOTI, {}) or {})
    if not presenze:
        n = tentativi.get(str(partita_id), 0) + 1
        if n >= TENTATIVI_VUOTI_MAX and campionato_di(partita.competizione_id) != SERIE_A:
            # fuori dalla Serie A non si insiste: la partita resta senza presenze
            log.warning(
                "Statistiche della partita %s vuote per %s volte: segnata come scaricata, "
                "senza presenze", partita_id, n,
            )
            partita.statistiche_scaricate = True
            tentativi.pop(str(partita_id), None)
        else:
            log.warning("Statistiche della partita %s vuote: riprovo la prossima volta", partita_id)
            tentativi[str(partita_id)] = n
        repo.scrivi_impostazione(s, TENTATIVI_VUOTI, tentativi)
        s.commit()
        return False
    for dati in presenze:
        _salva_presenza(s, dati)
    salva_stili_fonte(s, fonte)  # stemmi e colori dallo stesso summary
    partita.gialli_totali = sum(p.gialli for p in presenze)  # panchina compresa
    partita.rossi_totali = sum(p.rossi for p in presenze)
    partita.falli_totali = sum(p.falli_commessi for p in presenze)
    partita.statistiche_scaricate = True
    if tentativi.pop(str(partita_id), None) is not None:
        repo.scrivi_impostazione(s, TENTATIVI_VUOTI, tentativi)
    s.commit()
    return True


def aggiorna_calendario(
    s: Session, fonte: Fonte, stagione: int = STAGIONE_CORRENTE, competizione_id: int = SERIE_A
) -> int:
    """Partite del campionato (Serie A se non indicato) della stagione (1 richiesta).
    Restituisce quante ne ha salvate."""
    partite = fonte.partite(competizione_id, stagione)
    for dati in partite:
        salva_partita(s, dati)
    s.commit()
    return len(partite)


def scarica_statistiche_giocate(
    s: Session, fonte: Fonte, adesso: datetime, competizione_id: int = SERIE_A
) -> int:
    """Statistiche delle partite del campionato (Serie A se non indicato) della stagione
    corrente finite negli ultimi 7 giorni e non ancora scaricate, dalla più recente. Il resto
    (coppe, stagioni passate, partite più vecchie) resta allo storico, con priorità STORICO:
    il job notturno non deve consumare il budget del giorno (spec §3.3).
    Restituisce quante ne ha scaricate; su LimiteSuperato il lavoro già fatto resta salvato."""
    ids = s.scalars(
        select(Partita.id)
        .where(
            Partita.competizione_id == competizione_id,
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


def collega_arbitri(s: Session, fonte_fd, adesso: datetime) -> bool:
    """Arbitri da football-data.org per le partite di ogni campionato (la Serie A per prima)
    tra 7 giorni fa e fra 7 giorni. Senza chiave `collega` salta e lo scrive nel log (esito
    normale, True). Un errore della fonte viene registrato nel log: le partite di quel
    campionato restano senza arbitro (fattore neutro), gli altri campionati proseguono e il
    risultato è False."""
    completo = True
    for campionato in CAMPIONATI:
        try:
            arbitri_fd.collega(
                s,
                fonte_fd,
                campionato,
                (adesso - timedelta(days=GIORNI_ARBITRI)).date(),
                (adesso + timedelta(days=GIORNI_ARBITRI)).date(),
            )
        except (ErroreFonte, LimiteSuperato) as errore:
            s.rollback()
            log.warning("Arbitri %s non collegati: %s", NOMI_CAMPIONATI[campionato], errore)
            completo = False
    return completo


def esegui(
    s: Session,
    fonte: Fonte,
    adesso: datetime | None = None,
    fonte_fd=None,
    controllo=None,
) -> RiepilogoJob:
    """Controllo di salute (se dato), calendario, statistiche, arbitri (se c'e' `fonte_fd`),
    esiti delle giocate; poi segna l'aggiornamento "notte".
    `controllo(fonte) -> list[str]` restituisce i problemi di struttura della fonte: se ce ne
    sono il job li scrive nel log e termina con completo=False, ma il resto viene fatto.
    Se il limite di richieste finisce a metà, salva il parziale e restituisce completo=False.
    Un ErroreFonte sul calendario viene registrato nel log: statistiche ed esiti proseguono
    con le partite già note e l'aggiornamento risulta incompleto."""
    adesso = adesso or datetime.now(timezone.utc)
    contata = FonteContata(fonte)
    completo = True
    try:
        if controllo is not None:
            try:
                problemi = controllo(fonte)
            except LimiteSuperato:
                raise
            except Exception as errore:  # noqa: BLE001 - il controllo non deve fermare il job
                problemi = [f"struttura inattesa: {errore!r}"]
            if problemi:
                log.error("La struttura dei dati ESPN è cambiata: %s", "; ".join(problemi))
                completo = False
        # un campionato alla volta, la Serie A per prima: se il budget finisce, la Serie A è fatta
        for campionato in CAMPIONATI:
            try:
                aggiorna_calendario(s, contata, competizione_id=campionato)
            except ErroreFonte as errore:
                log.warning("Calendario %s non aggiornato: %s", NOMI_CAMPIONATI[campionato], errore)
                completo = False
            scarica_statistiche_giocate(s, contata, adesso, campionato)
    except LimiteSuperato:
        s.commit()
        completo = False
    if fonte_fd is not None and not collega_arbitri(s, fonte_fd, adesso):
        completo = False
    aggiorna_esiti(s)
    repo.segna_aggiornamento(s, "notte", completo)
    s.commit()
    return RiepilogoJob(contata.richieste, contata.statistiche_ricevute, completo)
