"""Manutenzione una tantum: ricarica le statistiche delle partite con sostituti a 0 minuti.

Le partite caricate prima della correzione dei minuti di recupero possono avere sostituti
salvati con minuti = 0 pur essendo entrati (hanno falli, tiri, gol o assist). Lo script
seleziona le partite (di qualsiasi competizione) con almeno una presenza non titolare, a 0
minuti e con attivita' in campo, e ne stampa il numero.

Uso: python scripts/ricarica_minuti.py            (prova: stampa solo quante sono)
     python scripts/ricarica_minuti.py --esegui   (riscarica e salva le statistiche)

Il salvataggio usa `caricamento.notturno.scarica_statistiche_partita`, che sovrascrive le
presenze anche se la partita risulta gia' scaricata.
"""
import argparse
import sys

from sqlalchemy import select

from ammonizioni.caricamento import notturno
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Presenza
from ammonizioni.fonti.limite import LimiteSuperato, Priorita
from ammonizioni.scheduler.comune import ErroreConfigurazione, crea_fonte as crea_fonte_predefinita


def partite_da_ricaricare(s) -> list[int]:
    """Id (ordinati) delle partite con un sostituto a 0 minuti e con attivita' in campo."""
    attivita = (
        Presenza.falli_commessi + Presenza.falli_subiti + Presenza.tiri + Presenza.gol
        + Presenza.assist
    )
    return list(
        s.scalars(
            select(Presenza.partita_id)
            .where(Presenza.titolare.is_(False), Presenza.minuti == 0, attivita > 0)
            .distinct()
            .order_by(Presenza.partita_id)
        )
    )


def main(argv=None, crea_fonte=crea_fonte_predefinita, apri=modulo_sessione.apri) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--esegui", action="store_true", help="riscarica davvero le partite (senza: prova)"
    )
    args = parser.parse_args(argv)

    with apri() as s:
        ids = partite_da_ricaricare(s)
        print(f"Partite con sostituti a 0 minuti da ricaricare: {len(ids)}")
        if not args.esegui or not ids:
            if ids:
                print("Prova: nessuna modifica. Aggiungi --esegui per ricaricarle.")
            return 0
        try:
            fonte = crea_fonte(s, Priorita.STORICO)
        except ErroreConfigurazione as errore:
            print(errore, file=sys.stderr)
            return 2
        ricaricate = 0
        try:
            for i, partita_id in enumerate(ids, 1):
                if notturno.scarica_statistiche_partita(s, fonte, partita_id):
                    ricaricate += 1
                if i % 20 == 0 or i == len(ids):
                    print(f"  ... {i}/{len(ids)} partite", flush=True)
        except LimiteSuperato:
            print("Limite di richieste raggiunto: rilancia lo script piu' tardi.")
        print(f"Ricaricate: {ricaricate}/{len(ids)}")
        return 0 if ricaricate == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
