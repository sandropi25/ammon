"""Job notturno: aggiornamento dati (priorita' OGGI) e poi storico con il budget rimasto.
Lancio: `python -m ammonizioni.scheduler.notte`."""
from __future__ import annotations

import logging

from ammonizioni import config
from ammonizioni.caricamento import biografie as biografie_giocatori
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


def aggiorna_biografie(s):
    """Biografie dei giocatori (ESPN + Wikipedia), poche per notte. L'anagrafica ESPN usa lo
    stesso limite di richieste del job; con API-Football gli id non sono ESPN: solo Wikipedia."""
    espn = config.fonte_dati() == "espn"
    limite = s.info.setdefault("limite_espn", crea_limite_espn(s)) if espn else None
    return biografie_giocatori.aggiorna(s, ClientBiografie(limite), usa_espn=espn)


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
        riepilogo = notturno.esegui(
            s, fonte_oggi, fonte_fd=fonte_fd, controllo=controllo if espn else None
        )
        log.info(
            "Notte: %s richieste, %s partite aggiornate, completo=%s",
            riepilogo.richieste_usate, riepilogo.partite_aggiornate, riepilogo.completo,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
