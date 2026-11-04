"""Job notturno: aggiornamento dati (priorita' OGGI) e poi storico con il budget rimasto.
Lancio: `python -m ammonizioni.scheduler.notte`."""
from __future__ import annotations

import logging

from ammonizioni import config
from ammonizioni.caricamento import notturno, storico
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.fonti.limite import Priorita
from ammonizioni.scheduler.comune import configura_log, crea_api_football, crea_limite

log = logging.getLogger(__name__)


def main(argv=None, crea_fonte=crea_api_football) -> int:
    configura_log()
    with modulo_sessione.apri() as s:
        chiave = config.chiave_api(s)
        if not chiave:
            log.error("Chiave API-Football mancante (API_FOOTBALL_KEY o impostazione 'chiave_api')")
            return 2
        limite = crea_limite(s)  # uno solo: le due fonti condividono il ritmo al minuto
        riepilogo = notturno.esegui(s, crea_fonte(chiave, Priorita.OGGI, limite))
        log.info(
            "Notte: %s richieste, %s partite aggiornate, completo=%s",
            riepilogo.richieste_usate, riepilogo.partite_aggiornate, riepilogo.completo,
        )
        riepilogo = storico.avanza(s, crea_fonte(chiave, Priorita.STORICO, limite))
        log.info(
            "Storico: %s richieste, %s partite aggiornate, completo=%s",
            riepilogo.richieste_usate, riepilogo.partite_aggiornate, riepilogo.completo,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
