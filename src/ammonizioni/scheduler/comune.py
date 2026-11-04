"""Parti comuni ai punti di ingresso dello scheduler."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ammonizioni.fonti.api_football import ApiFootball
from ammonizioni.fonti.base import Fonte
from ammonizioni.fonti.limite import LimiteRichieste, Priorita


def configura_log() -> None:
    logging.basicConfig(level=logging.INFO)


def crea_api_football(s: Session, chiave: str, priorita: Priorita) -> Fonte:
    """Client API-Football; il contatore giornaliero e' nel database (condiviso fra i job)."""
    return ApiFootball(chiave, LimiteRichieste(s), priorita=priorita)
