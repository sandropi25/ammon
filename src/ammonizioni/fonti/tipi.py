"""Tipi di scambio tra le fonti dati e il resto dell'applicazione."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class StileSquadra:
    """Stemma e colori di una squadra (ESPN `team.logo`, `color`, `alternateColor`): URL
    https e colori "#RRGGBB"; None dove la fonte non li dà."""
    logo_url: str | None = None
    colore: str | None = None
    colore_alt: str | None = None


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
    # stemma e colori delle due squadre, se la fonte li dà (ESPN: nello scoreboard)
    casa_stile: StileSquadra | None = None
    trasferta_stile: StileSquadra | None = None
    # cartellini e falli totali della partita dal tabellone ESPN (None: il tabellone non li dà)
    gialli_totali: int | None = None
    rossi_totali: int | None = None
    falli_totali: int | None = None


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
    maglia: int | None = None  # numero di maglia (ESPN `jersey`), se noto


@dataclass(frozen=True)
class FormazioneDati:
    partita_id: int
    squadra_id: int
    # (giocatore_id, nome, ruolo, griglia)
    titolari: list[tuple[int, str, str | None, str | None]]
    # panchinari in distinta (giocatore_id, nome, ruolo): servono per i probabili subentranti
    panchina: list[tuple[int, str, str | None]] = field(default_factory=list)
    # numeri di maglia (giocatore_id -> numero) di titolari e panchina, se noti
    maglie: dict[int, int] = field(default_factory=dict)
