"""Job notturno: aggiornamento dati (priorita' OGGI) e poi storico con il budget rimasto.
Lancio: `python -m ammonizioni.scheduler.notte`."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ammonizioni import config
from ammonizioni.caricamento import biografie as biografie_giocatori
from ammonizioni.caricamento.foto import aggiorna_foto_senza_errori
from ammonizioni.caricamento import notturno, storico
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.fonti.biografie import ClientBiografie
from ammonizioni.fonti.controllo_espn import controlla_struttura
from ammonizioni.fonti.espn import crea_limite_espn
from ammonizioni.fonti.limite import Priorita
from ammonizioni.scheduler.comune import (
    ErroreConfigurazione,
    configura_log,
    crea_football_data,
    crea_fonte as crea_fonte_predefinita,
)

log = logging.getLogger(__name__)

LIMITE_FOTO = 300  # ricerche di foto per notte (circa 11 minuti a 2,2 s l'una)


def aggiorna_biografie(s):
    """Biografie dei giocatori (ESPN + Wikipedia), poche per notte. L'anagrafica ESPN usa lo
    stesso limite di richieste del job; con API-Football gli id non sono ESPN: solo Wikipedia."""
    espn = config.fonte_dati() == "espn"
    limite = s.info.setdefault("limite_espn", crea_limite_espn(s)) if espn else None
    return biografie_giocatori.aggiorna(s, ClientBiografie(limite), usa_espn=espn)


def aggiorna_tutto(
    s, fonte_oggi, fonte_storico, fonte_fd, controllo, biografie, adesso=None, etichetta="Notte"
) -> None:
    """Calendario, statistiche, arbitri, esiti; biografie; storico col suo tetto di tempo.
    Usato dal job settimanale e dall'aggiornamento della giornata dell'orchestratore."""
    riepilogo = notturno.esegui(
        s, fonte_oggi, adesso=adesso, fonte_fd=fonte_fd, controllo=controllo
    )
    log.info(
        "%s: %s richieste, %s partite aggiornate, completo=%s",
        etichetta, riepilogo.richieste_usate, riepilogo.partite_aggiornate, riepilogo.completo,
    )
    try:
        bio = biografie(s)
        log.info(
            "Biografie: %s giocatori controllati (%s con anagrafica, %s con Wikipedia), "
            "completo=%s", bio.controllati, bio.con_anagrafica, bio.con_wikipedia,
            bio.completo,
        )
    except Exception:  # noqa: BLE001 - le biografie non devono fermare il job
        s.rollback()
        log.exception("Biografie non aggiornate")
    riepilogo = storico.avanza(s, fonte_storico, fonte_fd)
    log.info(
        "Storico: %s richieste, %s partite aggiornate, completo=%s",
        riepilogo.richieste_usate, riepilogo.partite_aggiornate, riepilogo.completo,
    )


def main(
    argv=None,
    crea_fonte=crea_fonte_predefinita,
    crea_fd=crea_football_data,
    controllo=controlla_struttura,
    biografie=None,
) -> int:
    biografie = biografie or aggiorna_biografie
    configura_log()
    with modulo_sessione.apri() as s:
        try:
            fonte_oggi = crea_fonte(s, Priorita.OGGI)
            fonte_storico = crea_fonte(s, Priorita.STORICO)
        except ErroreConfigurazione as errore:
            log.error("%s", errore)
            return 2
        espn = config.fonte_dati() == "espn"
        # con API-Football gli arbitri arrivano gia' dalla fonte: football-data non serve
        fonte_fd = crea_fd(s) if espn else None
        # il controllo di salute vale solo per ESPN (API non ufficiale)
        aggiorna_tutto(
            s, fonte_oggi, fonte_storico, fonte_fd, controllo if espn else None, biografie
        )
        # foto (TheSportsDB): a parte, per ultime; i giocatori delle prossime partite per primi
        aggiorna_foto_senza_errori(s, datetime.now(timezone.utc), limite=LIMITE_FOTO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
