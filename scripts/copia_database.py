"""Copia tutto il database (es. quello locale SQLite) in un altro database vuoto
(es. Postgres su Supabase), così online non serve riscaricare lo storico da ESPN.

Uso:
    python scripts/copia_database.py --da sqlite:///ammonizioni.db --a-variabile DATABASE_URL_SUPABASE

La destinazione si passa con il nome di una variabile d'ambiente, così la stringa
di connessione (che contiene la password) non compare mai sulla riga di comando né
nell'output. La destinazione non deve contenere partite (eventuali righe di servizio
scritte dai job su un database vuoto vengono sostituite).
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import func, insert, select, text

from ammonizioni import config
from ammonizioni.db.modelli import Base
from ammonizioni.db.sessione import crea_engine, crea_tabelle

BLOCCO = 2000  # righe per inserimento


def _normalizza(url: str) -> str:
    vecchio = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        return config.url_database()  # postgres:// -> postgresql+psycopg://
    finally:
        if vecchio is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = vecchio


def copia(url_origine: str, url_destinazione: str, stampa=lambda *_: None) -> dict[str, int]:
    origine = crea_engine(_normalizza(url_origine))
    destinazione = crea_engine(_normalizza(url_destinazione))
    try:
        return _copia(origine, destinazione, stampa)
    finally:  # chiude le connessioni (niente ResourceWarning)
        origine.dispose()
        destinazione.dispose()


def _copia(origine, destinazione, stampa) -> dict[str, int]:
    crea_tabelle(destinazione)
    tabelle = Base.metadata.sorted_tables  # prima le tabelle a cui le altre fanno riferimento
    partite = Base.metadata.tables["partite"]
    with destinazione.connect() as d:
        if d.execute(select(func.count()).select_from(partite)).scalar():
            raise SystemExit("Il database di destinazione non e' vuoto (ci sono gia' partite).")
    copiate: dict[str, int] = {}
    with origine.connect() as o, destinazione.begin() as d:
        # senza partite ci possono essere solo righe di servizio (es. scritte da un job
        # pre-partita su un database vuoto): si cancellano e si copia tutto dall'origine
        for t in reversed(tabelle):
            d.execute(t.delete())
        for t in tabelle:
            righe = o.execute(select(t)).mappings()
            n = 0
            blocco = []
            for riga in righe:
                blocco.append(dict(riga))
                if len(blocco) >= BLOCCO:
                    d.execute(insert(t), blocco)
                    n += len(blocco)
                    blocco = []
                    stampa(f"  {t.name}: {n}")
            if blocco:
                d.execute(insert(t), blocco)
                n += len(blocco)
            copiate[t.name] = n
            stampa(f"{t.name}: {n} righe")
        if d.dialect.name == "postgresql":
            # i prossimi id automatici devono partire dopo quelli copiati
            for t in tabelle:
                pk = list(t.primary_key.columns)
                if len(pk) == 1 and pk[0].autoincrement is not False and pk[0].type.python_type is int:
                    col = pk[0].name
                    d.execute(text(
                        f"select setval(pg_get_serial_sequence('{t.name}', '{col}'), "
                        f"coalesce((select max({col}) from {t.name}), 0) + 1, false) "
                        f"where pg_get_serial_sequence('{t.name}', '{col}') is not null"
                    ))
    return copiate


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Copia il database in un database vuoto.")
    p.add_argument("--da", default="sqlite:///ammonizioni.db", help="URL di origine")
    p.add_argument("--a-variabile", required=True,
                   help="nome della variabile d'ambiente con l'URL di destinazione")
    a = p.parse_args(argv)
    url = os.environ.get(a.a_variabile, "").strip().strip('"')
    if not url:
        print(f"La variabile {a.a_variabile} non e' impostata.", file=sys.stderr)
        return 2
    copiate = copia(a.da, url, stampa=lambda m: print(m, flush=True))
    print(f"Copia completata: {sum(copiate.values())} righe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
