"""Prova sulla scorsa stagione: confronta il modello con la scelta semplice.

Uso: python scripts/prova_stagione.py --stagione 2025 [--k 3] [--campionato 135|140]
     [--solo-titolari]  (senza i probabili subentranti, per confrontare con prima)
     [--modello V1|V2]  (V2: coefficienti salvati; per la prova fuori campione con Brier,
                         log-loss e decili usa scripts/prova_v2.py)
Richiede lo storico gia' caricato nel database.
"""
import argparse
import sys

from ammonizioni.backtest.prova import Copertura, RisultatoProva, copertura, prova_stagione
from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI
from ammonizioni.db.sessione import apri


def percentuale(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",") + "%"


def stampa_tabella(
    r: RisultatoProva, stagione: int, k: int, campionato: int = 135, c: Copertura | None = None
) -> None:
    nome = NOMI_CAMPIONATI.get(campionato, str(campionato))
    chi = "solo titolari" if r.solo_titolari else "titolari e probabili subentranti"
    print(f"Prova sulla stagione {stagione} - {nome} (primi {k} candidati per partita, {chi})")
    print(f"Partite valutate: {r.partite}")
    if c is not None:
        print(
            f"Con arbitro: {c.con_arbitro}/{c.partite}; "
            f"con griglia dei titolari: {c.con_griglia}/{c.partite}"
        )
    print()
    print(f"{'Metodo':<26}{'Successi':>10}{'Tasso':>10}")
    print(f"{'Modello':<26}{r.successi_modello:>10}{percentuale(r.tasso_modello):>10}")
    print(f"{'Scelta semplice':<26}{r.successi_base:>10}{percentuale(r.tasso_base):>10}")
    if not r.solo_titolari:
        print()
        print(f"Successi del modello di cui subentranti nei primi {k}: {r.successi_subentranti}")
        print(f"Partite con un subentrante nei primi {k}: {r.partite_con_subentranti}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stagione", type=int, required=True, help="anno di inizio, es. 2025")
    parser.add_argument("--k", type=int, default=3, help="quanti candidati considerare")
    parser.add_argument(
        "--campionato", type=int, default=135, help="135 (Serie A, predefinito) o 140 (Liga)"
    )
    parser.add_argument(
        "--solo-titolari", action="store_true",
        help="come prima dei subentranti: i primi k scelti solo fra i titolari",
    )
    parser.add_argument(
        "--modello", choices=("V1", "V2"), default="V1",
        help="V1 (predefinito) o V2 con i coefficienti salvati (scripts/calibra_v2.py --salva)",
    )
    args = parser.parse_args(argv)
    if args.campionato not in CAMPIONATI:
        ammessi = " o ".join(str(c) for c in CAMPIONATI)
        print(
            f"Campionato {args.campionato} non valido: valori ammessi {ammessi} "
            "(135 = Serie A, 140 = Liga).",
            file=sys.stderr,
        )
        return 2

    def avanzamento(fatte: int, totale: int) -> None:
        if fatte % 20 == 0 or fatte == totale:
            print(f"  ... {fatte}/{totale} partite", flush=True)

    with apri() as s:
        r = prova_stagione(
            s, args.stagione, args.k, avanzamento=avanzamento, competizione_id=args.campionato,
            solo_titolari=args.solo_titolari, modello=args.modello,
        )
        c = copertura(s, args.stagione, args.campionato)

    if r.partite == 0:
        nome = NOMI_CAMPIONATI[args.campionato]
        print(
            f"Nessuna partita di {nome} trovata per la stagione {args.stagione}: "
            "carica prima lo storico (caricamento notturno o storico)."
        )
        return 1
    stampa_tabella(r, args.stagione, args.k, args.campionato, c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
