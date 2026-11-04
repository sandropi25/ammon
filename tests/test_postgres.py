"""Prova su Postgres reale (Supabase): saltata se DATABASE_URL non e' un URL Postgres.

Uso: impostare DATABASE_URL e lanciare `pytest -m postgres -v`.
Le tabelle vengono create in uno schema temporaneo, eliminato a fine prova: i dati
presenti nello schema pubblico del database non vengono toccati.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ammonizioni import config
from ammonizioni.db import sessione as modulo_sessione

# I test non sono pacchetti (pytest li importa per nome di file): per riusare i due test
# esistenti si aggiungono le loro cartelle al percorso di import.
for _cartella in ("db", "motore"):
    sys.path.insert(0, str(Path(__file__).parent / _cartella))

import test_dati  # noqa: E402
import test_modelli  # noqa: E402

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith("postgres"),
        reason="DATABASE_URL non e' un URL Postgres",
    ),
]


@pytest.fixture
def sessione_postgres():
    schema = f"prova_{uuid.uuid4().hex[:12]}"
    url = config.url_database()
    amministratore = create_engine(url, pool_pre_ping=True)
    with amministratore.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, pool_pre_ping=True, connect_args={"options": f"-csearch_path={schema}"}
    )
    try:
        modulo_sessione.crea_tabelle(engine)
        with Session(engine) as s:
            yield s
    finally:
        engine.dispose()
        with amministratore.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        amministratore.dispose()


def test_upsert_presenza_idempotente_su_postgres(sessione_postgres):
    test_modelli.test_upsert_presenza_idempotente(sessione_postgres)


def test_mercato_ammonizioni_end_to_end_su_postgres(sessione_postgres):
    test_dati.test_mercato_ammonizioni_end_to_end(sessione_postgres)
