"""Engine, creazione tabelle e sessioni."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ammonizioni import config
from ammonizioni.db.modelli import Base

# un Engine per URL, creato (con le tabelle) una volta sola per processo
_engines: dict[str, Engine] = {}
_lock = threading.Lock()


def crea_engine(url: str) -> Engine:
    if url in ("sqlite://", "sqlite:///:memory:"):
        # Database in memoria: stessa connessione per tutti i thread.
        return create_engine(
            url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    if url.startswith("postgresql"):
        # Supabase (pooler) chiude le connessioni inattive: pre-ping e riciclo prima della
        # chiusura; pochi collegamenti per processo (l'app ha pochi utenti contemporanei)
        return create_engine(
            url, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=280
        )
    return create_engine(url, pool_pre_ping=True)


# Colonne aggiunte dopo la prima versione: (tabella, colonna, tipo SQL). `create_all` non
# modifica le tabelle già esistenti, quindi si aggiungono qui, in modo idempotente.
COLONNE_AGGIUNTE: tuple[tuple[str, str, str], ...] = (
    ("partite", "prob_casa", "DOUBLE PRECISION"),
    ("partite", "prob_pareggio", "DOUBLE PRECISION"),
    ("partite", "prob_trasferta", "DOUBLE PRECISION"),
)


def _aggiungi_colonne_mancanti(engine: Engine) -> None:
    dialetto = engine.dialect.name
    with engine.begin() as conn:
        for tabella, colonna, tipo in COLONNE_AGGIUNTE:
            if dialetto == "postgresql":
                conn.execute(
                    text(f"ALTER TABLE {tabella} ADD COLUMN IF NOT EXISTS {colonna} {tipo}")
                )
            elif dialetto == "sqlite":
                presenti = {r[1] for r in conn.execute(text(f"PRAGMA table_info({tabella})"))}
                if colonna not in presenti:
                    conn.execute(text(f"ALTER TABLE {tabella} ADD COLUMN {colonna} {tipo}"))


def crea_tabelle(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _aggiungi_colonne_mancanti(engine)


def engine_per(url: str) -> Engine:
    """Engine dell'URL dalla cache del modulo; alla prima richiesta lo crea e crea le tabelle."""
    with _lock:
        engine = _engines.get(url)
        if engine is None:
            engine = crea_engine(url)
            crea_tabelle(engine)
            _engines[url] = engine
        return engine


def chiudi_engines() -> None:
    """Chiude e dimentica tutti gli engine in cache (fine processo o test)."""
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()


@contextmanager
def apri(url: str | None = None) -> Iterator[Session]:
    """Sessione che fa commit a fine blocco e rollback in caso di errore."""
    sessione = Session(engine_per(url or config.url_database()))
    try:
        yield sessione
        sessione.commit()
    except Exception:
        sessione.rollback()
        raise
    finally:
        sessione.close()
