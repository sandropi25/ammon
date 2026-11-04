"""Engine, creazione tabelle e sessioni."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ammonizioni import config
from ammonizioni.db.modelli import Base


def crea_engine(url: str) -> Engine:
    if url in ("sqlite://", "sqlite:///:memory:"):
        # Database in memoria: stessa connessione per tutti i thread.
        return create_engine(
            url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    return create_engine(url, pool_pre_ping=True)


def crea_tabelle(engine: Engine) -> None:
    Base.metadata.create_all(engine)


@contextmanager
def apri(url: str | None = None) -> Iterator[Session]:
    """Sessione che fa commit a fine blocco e rollback in caso di errore."""
    engine = crea_engine(url or config.url_database())
    crea_tabelle(engine)
    sessione = Session(engine)
    try:
        yield sessione
        sessione.commit()
    except Exception:
        sessione.rollback()
        raise
    finally:
        sessione.close()
        engine.dispose()
