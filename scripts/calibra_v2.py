"""Stima i coefficienti del modello V2 sulle stagioni scelte e stampa le diagnostiche.

Uso: python scripts/calibra_v2.py --stagioni 2024 2025 [--campionati 135 140]
     [--cache CARTELLA] [--l2-partita 2] [--l2-giocatore 2] [--salva]
Ogni partita vede solo i dati precedenti al suo calcio d'inizio. Con --salva i coefficienti
(con data e campione) vanno nelle impostazioni del database (chiave modello_v2_coefficienti):
il modello usato dall'app resta quello scelto in Impostazioni (V1 predefinito).
Con --cache le partite lette si salvano in file locali e la volta dopo si rileggono.
"""
import argparse
import sys
from pathlib import Path

from ammonizioni.backtest import v2 as bv2
from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI
from ammonizioni.db.sessione import apri
from ammonizioni.motore import modello


def leggi_partite(s, stagioni, campionati, cache):
    partite = []
    for campionato in campionati:
        for stagione in stagioni:
            nome = f"{NOMI_CAMPIONATI.get(campionato, campionato)} {stagione}"

            def avanzamento(fatte, totale, nome=nome):
                if fatte % 50 == 0 or fatte == totale:
                    print(f"  ... {nome}: {fatte}/{totale} partite", flush=True)

            righe = bv2.estrai_con_cache(s, stagione, campionato, cache, avanzamento)
            print(f"{nome}: {len(righe)} partite")
            partite += righe
    return partite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stagioni", type=int, nargs="+", required=True)
    parser.add_argument("--campionati", type=int, nargs="+", default=list(CAMPIONATI))
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--l2-partita", type=float, default=bv2.L2_PARTITA)
    parser.add_argument("--l2-giocatore", type=float, default=bv2.L2_GIOCATORE)
    parser.add_argument("--salva", action="store_true", help="salva i coefficienti nel database")
    args = parser.parse_args(argv)
    sconosciuti = [c for c in args.campionati if c not in CAMPIONATI]
    if sconosciuti:
        print(f"Campionati non validi: {sconosciuti} (135 = Serie A, 140 = Liga)", file=sys.stderr)
        return 2

    with apri() as s:
        partite = leggi_partite(s, args.stagioni, args.campionati, args.cache)
        if not partite:
            print("Nessuna partita con statistiche: carica prima lo storico.")
            return 1
        coeff = bv2.stima(partite, args.l2_partita, args.l2_giocatore)
        print()
        print(bv2.testo_coefficienti(coeff))
        for campionato in args.campionati:
            proprie = [p for p in partite if p.campionato == campionato]
            if proprie:
                print(bv2.testo_valutazione(
                    bv2.valuta(proprie, coeff),
                    f"Nel campione (non fuori campione): {NOMI_CAMPIONATI.get(campionato)}",
                ))
        if args.salva:
            modello.salva_coefficienti(s, coeff)
            s.commit()
            print("Coefficienti salvati nelle impostazioni (modello_v2_coefficienti).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
