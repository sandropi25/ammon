"""Funzioni di accesso ai dati."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ammonizioni.db.modelli import Impostazione, UltimoAggiornamento


def upsert(s: Session, oggetto):
    """Inserisce o aggiorna (via merge sulla chiave primaria) e restituisce l'istanza."""
    return s.merge(oggetto)


def leggi_impostazione(s: Session, chiave: str, default: Any = None) -> Any:
    riga = s.get(Impostazione, chiave)
    if riga is None:
        return default
    return riga.valore_json


def scrivi_impostazione(s: Session, chiave: str, valore: Any) -> None:
    s.merge(Impostazione(chiave=chiave, valore_json=valore))
    s.flush()


def segna_aggiornamento(s: Session, job: str, completo: bool) -> None:
    s.merge(
        UltimoAggiornamento(
            job=job, quando_utc=datetime.now(timezone.utc), completo=completo
        )
    )
    s.flush()


def ultimo_aggiornamento(s: Session, job: str) -> datetime | None:
    riga = s.get(UltimoAggiornamento, job)
    return riga.quando_utc if riga else None
