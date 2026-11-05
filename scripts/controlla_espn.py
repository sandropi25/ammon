"""Controllo di salute di ESPN: scarica una partita di Serie A nota (1 richiesta) e verifica che
ci siano i campi usati dal programma (roster, titolari, id e posizione dei giocatori,
statistiche, minuti degli eventi). Esce con 0 se e' tutto a posto, 1 se la struttura e'
cambiata. Lo esegue anche il job notturno.

    python scripts/controlla_espn.py
"""
import sys

import httpx

from ammonizioni.fonti.controllo_espn import PARTITA_CONTROLLO, controlla_struttura
from ammonizioni.fonti.espn import Espn


def main() -> int:
    with httpx.Client(timeout=30.0) as client:
        problemi = controlla_struttura(Espn(client=client))
    if problemi:
        print(f"La struttura dei dati ESPN è cambiata (partita {PARTITA_CONTROLLO}):")
        for problema in problemi:
            print(f"  - {problema}")
        return 1
    print(f"ESPN ok: la partita {PARTITA_CONTROLLO} ha tutti i campi usati dal programma.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
