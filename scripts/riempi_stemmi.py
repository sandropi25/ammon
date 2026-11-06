"""Manutenzione una tantum: stemmi e colori ESPN per le squadre già nel database.

D'ora in poi arrivano da soli con il calendario e le statistiche; questo script li riempie
per le squadre salvate prima, leggendo il calendario della stagione corrente di ogni
campionato (2 richieste ESPN per campionato). Le partite non vengono toccate.

Uso: python scripts/riempi_stemmi.py
"""
import sys

from ammonizioni.caricamento.stemmi import riempi_stemmi
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.fonti.limite import Priorita
from ammonizioni.scheduler.comune import ErroreConfigurazione, crea_fonte as crea_fonte_predefinita


def main(argv=None, crea_fonte=crea_fonte_predefinita, apri=modulo_sessione.apri) -> int:
    with apri() as s:
        try:
            fonte = crea_fonte(s, Priorita.STORICO)
        except ErroreConfigurazione as errore:
            print(errore, file=sys.stderr)
            return 2
        cambiate = riempi_stemmi(s, fonte)
    print(f"Squadre con stemma e colori aggiornati: {cambiate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
