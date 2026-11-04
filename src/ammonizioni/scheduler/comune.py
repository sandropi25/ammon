"""Parti comuni ai punti di ingresso dello scheduler."""
from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from ammonizioni.fonti.api_football import ApiFootball
from ammonizioni.fonti.base import Fonte
from ammonizioni.fonti.limite import LimiteRichieste, Priorita

RICHIESTE_GIORNO = 100  # piano gratuito API-Football
RISERVA_OGGI = 30


def configura_log() -> None:
    logging.basicConfig(level=logging.INFO)


def _intero_da_env(nome: str, predefinito: int) -> int:
    valore = os.environ.get(nome, "").strip()
    return int(valore) if valore else predefinito


def crea_limite(s: Session) -> LimiteRichieste:
    """Limite richieste del job: uno solo per tutte le fonti del processo, cosi' il ritmo
    al minuto e' condiviso. Il contatore giornaliero e' nel database (condiviso fra i job).
    Tetto giornaliero e riserva per l'uso di oggi da API_RICHIESTE_GIORNO (default 100)
    e API_RISERVA_OGGI (default 30), per esempio per il piano Pro (7500 al giorno)."""
    return LimiteRichieste(
        s,
        max_giorno=_intero_da_env("API_RICHIESTE_GIORNO", RICHIESTE_GIORNO),
        riserva_oggi=_intero_da_env("API_RISERVA_OGGI", RISERVA_OGGI),
    )


def crea_api_football(chiave: str, priorita: Priorita, limite: LimiteRichieste) -> Fonte:
    """Client API-Football con il limite (condiviso) dato."""
    return ApiFootball(chiave, limite, priorita=priorita)
