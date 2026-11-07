"""Carica le foto (TheSportsDB) dei giocatori con presenze nella stagione corrente: prima la
Serie A, poi la Liga. Si può fermare e rilanciare: chi è già stato controllato (da meno di
30 giorni senza foto, da meno di 90 con la foto) viene saltato. Una ricerca ogni 2,2 secondi
(limite gratuito di TheSportsDB); con una risposta 429 si ferma.

Uso: python scripts/carica_foto.py [--limite N]   (usa DATABASE_URL come gli altri script)
"""
import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from ammonizioni.caricamento.foto import aggiorna_foto, da_cercare
from ammonizioni.config import NOMI_CAMPIONATI, SERIE_A, STAGIONE_CORRENTE, CAMPIONATI
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Partita, Presenza
from ammonizioni.fonti import foto as fonti_foto

SENZA_LIMITE = 10**9


def giocatori_del_campionato(s, campionato: int, stagione: int = STAGIONE_CORRENTE) -> set[int]:
    return {
        int(g)
        for g in s.scalars(
            select(Presenza.giocatore_id)
            .join(Partita, Partita.id == Presenza.partita_id)
            .where(Partita.competizione_id == campionato, Partita.stagione == stagione)
            .distinct()
        )
    }


def main(argv=None, crea_client=fonti_foto.crea_client, apri=modulo_sessione.apri) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limite", type=int, default=SENZA_LIMITE,
                        help="massimo di giocatori da cercare per campionato")
    args = parser.parse_args(argv)
    ordine = sorted(CAMPIONATI, key=lambda c: c != SERIE_A)  # Serie A per prima
    client = crea_client()
    totale = 0
    try:
        with apri() as s:
            for campionato in ordine:
                nome = NOMI_CAMPIONATI[campionato]
                ids = giocatori_del_campionato(s, campionato)
                adesso = datetime.now(timezone.utc)
                da_fare = len(da_cercare(s, adesso, SENZA_LIMITE, solo_ids=ids))
                print(f"{nome}: {len(ids)} giocatori, {da_fare} da cercare", flush=True)

                def avanzamento(fatti, quanti, giocatore, nome=nome):
                    stato = "foto" if giocatore.foto_url else "-"
                    print(f"  {nome} {fatti}/{quanti} {giocatore.nome}: {stato}", flush=True)

                fatti = aggiorna_foto(
                    s, client, adesso, limite=args.limite, solo_ids=ids, avanzamento=avanzamento
                )
                totale += fatti
                if fatti < min(da_fare, args.limite):
                    print("Fermato (limite di richieste di TheSportsDB): rilancia più tardi.")
                    break
    finally:
        client.close()
    print(f"Giocatori controllati: {totale}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
