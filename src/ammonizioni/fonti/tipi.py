"""Tipi di scambio tra le fonti dati e il resto dell'applicazione."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PartitaDati:
    id: int
    data_utc: datetime  # aware UTC
    competizione_id: int
    stagione: int
    giornata: int | None
    casa_id: int
    casa_nome: str
    trasferta_id: int
    trasferta_nome: str
    arbitro_nome: str | None
    gol_casa: int | None
    gol_trasferta: int | None
    stato: str


@dataclass(frozen=True)
class PresenzaDati:
    partita_id: int
    giocatore_id: int
    giocatore_nome: str
    squadra_id: int
    titolare: bool
    ruolo: str | None
    griglia: str | None
    minuti: int
    gialli: int
    rossi: int
    falli_commessi: int
    falli_subiti: int
    dribbling_tentati: int
    dribbling_riusciti: int
    tiri: int
    gol: int
    assist: int
    voto: float | None


@dataclass(frozen=True)
class FormazioneDati:
    partita_id: int
    squadra_id: int
    # (giocatore_id, nome, ruolo, griglia)
    titolari: list[tuple[int, str, str | None, str | None]]
