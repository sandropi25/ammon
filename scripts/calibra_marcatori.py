"""Verifica e calibrazione del modello marcatori (beta).

Uso: python scripts/calibra_marcatori.py [--allena 2024] [--prova 2025 2026] [--salva]
Stampa le misure sulla prova (modello senza e con fattori, scelta semplice), per campionato.
Con --salva stima i pesi su allenamento + prova e li scrive in Impostazione
`marcatori_coefficienti` (l'app beta e i job li leggono da li')."""
import argparse
import sys
from datetime import datetime, timezone

from ammonizioni.config import NOMI_CAMPIONATI
from ammonizioni.db import repo
from ammonizioni.db.sessione import apri
from ammonizioni.marcatori import dati, verifica
from ammonizioni.marcatori.modello import CHIAVE_COEFFICIENTI, Parametri
from ammonizioni.motore.rivalita import derby_noti


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--allena", type=int, nargs="+", default=[2024])
    parser.add_argument("--prova", type=int, nargs="+", default=[2025, 2026])
    parser.add_argument("--salva", action="store_true")
    args = parser.parse_args(argv)
    with apri() as s:
        partite, presenze = dati.carica(s)
        derby = derby_noti(s)
        righe = verifica.percorri(partite, presenze, Parametri(), derby)
        allena = [r for r in righe if r.stagione in args.allena]
        prova = [r for r in righe if r.stagione in args.prova]
        for nome, sotto in [("Tutti", prova)] + [
            (NOMI_CAMPIONATI.get(c, c), [r for r in prova if r.competizione_id == c])
            for c in sorted({r.competizione_id for r in prova})
        ]:
            risultati, _ = verifica.confronta(allena, sotto)
            print(nome)
            for metodo, m in risultati.items():
                print(f"  {metodo:16} partite {m.partite:5}  log-loss {m.log_loss:.4f}  "
                      f"scarto {m.scarto_calibrazione:.3f}  almeno uno dei primi 3 {m.primi_almeno_uno:.1%}"
                      f"  primo {m.primo_segna:.1%}")
        if args.salva:
            par = verifica.stima(allena + prova, Parametri())
            valore = par.a_json() | {
                "stimati_utc": datetime.now(timezone.utc).isoformat(),
                "stagioni": sorted(set(args.allena + args.prova)),
                "righe": len(allena + prova),
            }
            repo.scrivi_impostazione(s, CHIAVE_COEFFICIENTI, valore)
            s.commit()
            print("Salvati:", par)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
