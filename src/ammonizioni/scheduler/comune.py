"""Parti comuni ai punti di ingresso dello scheduler."""
from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni import config
from ammonizioni.db import repo
from ammonizioni.db.modelli import Partita
from ammonizioni.fonti.api_football import ApiFootball
from ammonizioni.fonti.base import Fonte
from ammonizioni.fonti.espn import Espn, crea_limite_espn
from ammonizioni.fonti.football_data import FootballData
from ammonizioni.fonti.limite import (
    LimiteRichieste,
    Priorita,
    crea_limite_football_data,
)

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


class ErroreConfigurazione(Exception):
    """Configurazione mancante o non valida (per esempio la chiave di API-Football)."""


CHIAVE_FONTE_DB = "fonte_dati_db"


def verifica_fonte_database(s: Session, configurata: str) -> None:
    """La fonte dati di un database non si cambia: gli id di ESPN e di API-Football si
    sovrappongono (squadre e giocatori diversi con lo stesso id) e i dati si mescolerebbero.
    Alla prima volta la fonte configurata e' memorizzata (impostazione 'fonte_dati_db'). Un
    database con partite ma senza valore memorizzato (creato prima di questo controllo) si
    considera ESPN. ErroreConfigurazione se la fonte configurata e' diversa."""
    memorizzata = repo.leggi_impostazione(s, CHIAVE_FONTE_DB, None)
    if memorizzata is None:
        ha_partite = s.scalars(select(Partita.id).limit(1)).first() is not None
        memorizzata = "espn" if ha_partite else configurata
        if memorizzata == configurata:
            repo.scrivi_impostazione(s, CHIAVE_FONTE_DB, configurata)
    if memorizzata != configurata:
        raise ErroreConfigurazione(
            f"Il database contiene dati di {memorizzata}: per cambiare fonte serve "
            "un database nuovo e vuoto"
        )


def crea_fonte(s: Session, priorita: Priorita) -> Fonte:
    """Fonte dati scelta da FONTE_DATI: ESPN (predefinita, senza chiave) o API-Football.
    Il limite di richieste e' uno solo per sessione (e quindi per processo): le fonti create
    con priorita' diverse condividono il ritmo al minuto. Con API-Football la chiave e'
    obbligatoria (ErroreConfigurazione se manca). La fonte deve essere quella dei dati gia'
    presenti nel database (ErroreConfigurazione altrimenti)."""
    verifica_fonte_database(s, config.fonte_dati())
    if config.fonte_dati() == "api_football":
        chiave = config.chiave_api(s)
        if not chiave:
            raise ErroreConfigurazione(
                "Chiave API-Football mancante (API_FOOTBALL_KEY o impostazione 'chiave_api')"
            )
        limite = s.info.setdefault("limite_api_football", crea_limite(s))
        return crea_api_football(chiave, priorita, limite)
    limite = s.info.setdefault("limite_espn", crea_limite_espn(s))
    return Espn(limite, priorita=priorita)


def crea_football_data(s: Session) -> FootballData:
    """Client football-data.org (arbitri). Senza chiave (FOOTBALL_DATA_KEY o impostazione
    'chiave_football_data') e' comunque creato: `arbitri_fd.collega` salta e lo scrive nel log."""
    limite = s.info.setdefault("limite_football_data", crea_limite_football_data())
    return FootballData(config.chiave_football_data(s), limite)
