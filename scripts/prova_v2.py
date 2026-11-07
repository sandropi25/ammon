"""Prova fuori campione: V1, V2 e scelta semplice sulla stessa stagione.

Uso: python scripts/prova_v2.py --addestra 2024 --prova 2025 [--campionati 135 140]
     [--cache CARTELLA] [--k 3]
I coefficienti di V2 si stimano sulle stagioni --addestra (tutti i campionati scelti) e si
provano sulla stagione --prova, campionato per campionato. Stampa primi k, Brier, log-loss,
calibrazione per decili e somma delle probabilità contro i gialli reali per partita.
"""
import argparse
import sys
from pathlib import Path

from calibra_v2 import leggi_partite

from ammonizioni.backtest import v2 as bv2
from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI
from ammonizioni.db.sessione import apri


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--addestra", type=int, nargs="+", required=True)
    parser.add_argument("--prova", type=int, required=True)
    parser.add_argument("--campionati", type=int, nargs="+", default=list(CAMPIONATI))
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--l2-partita", type=float, default=bv2.L2_PARTITA)
    parser.add_argument("--l2-giocatore", type=float, default=bv2.L2_GIOCATORE)
    args = parser.parse_args(argv)
    if args.prova in args.addestra:
        print("La stagione di prova non può stare fra quelle di stima.", file=sys.stderr)
        return 2

    with apri() as s:
        stima = leggi_partite(s, args.addestra, args.campionati, args.cache)
        prova = leggi_partite(s, [args.prova], args.campionati, args.cache)
    if not stima or not prova:
        print("Mancano partite per la stima o per la prova.")
        return 1
    coeff = bv2.stima(stima, args.l2_partita, args.l2_giocatore)
    print()
    print(bv2.testo_coefficienti(coeff))
    for campionato in args.campionati:
        proprie = [p for p in prova if p.campionato == campionato]
        if not proprie:
            continue
        stagioni = "+".join(map(str, args.addestra))
        print(bv2.testo_valutazione(
            bv2.valuta(proprie, coeff, args.k),
            f"{NOMI_CAMPIONATI.get(campionato)} {args.prova} (V2 stimato su {stagioni})",
            args.k,
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
