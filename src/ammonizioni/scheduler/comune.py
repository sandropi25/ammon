"""Parti comuni ai punti di ingresso dello scheduler."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ammonizioni.fonti.api_football import ApiFootball
from ammonizioni.fonti.base import Fonte
from ammonizioni.fonti.limite import LimiteRichieste, Priorita


def configura_log() -> None:
    logging.basicConfig(level=logging.INFO)


def crea_limite(s: Session) -> LimiteRichieste:
    """Limite richieste del job: uno solo per tutte le fonti del processo, cosi' il ritmo
    al minuto e' condiviso. Il contatore giornaliero e' nel database (condiviso fra i job)."""
    return LimiteRichieste(s)


def crea_api_football(chiave: str, priorita: Priorita, limite: LimiteRichieste) -> Fonte:
    """Client API-Football con il limite (condiviso) dato."""
    return ApiFootball(chiave, limite, priorita=priorita)
