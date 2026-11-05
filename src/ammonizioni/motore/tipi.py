from dataclasses import dataclass
from datetime import datetime
from typing import Literal

RUOLI = ("G", "D", "M", "F")  # portiere, difensore, centrocampista, attaccante


def decimale(x: float, cifre: int = 1) -> str:
    """Formatta con la virgola decimale all'italiana: 5.4 -> "5,4"."""
    return f"{x:.{cifre}f}".replace(".", ",")


@dataclass(frozen=True)
class RigaPresenza:
    partita_id: int
    data: datetime
    stagione: int
    competizione_id: int
    squadra_id: int
    avversario_id: int
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
    titolare: bool
    rivalita: bool


@dataclass(frozen=True)
class MedieRuolo:
    gialli90: float
    falli90: float
    falli_subiti90: float
    dribbling90: float
    ga90: float
    voto: float


@dataclass(frozen=True)
class MedieCampionato:
    gialli_partita: float
    falli_partita: float
    per_ruolo: dict[str, MedieRuolo]


@dataclass(frozen=True)
class StatArbitro:
    nome: str
    partite: int
    gialli_medi: float
    falli_medi: float
    gialli_medi_con: dict[int, tuple[float, int]]


@dataclass(frozen=True)
class ContestoInfo:
    rivalita: bool
    campo_caldo: bool
    posta: dict[int, str | None]  # "titolo" / "Europa" / "salvezza"
    precedenti_n: int
    precedenti_gialli_medi: float | None


@dataclass(frozen=True)
class Titolare:
    giocatore_id: int
    nome: str
    squadra_id: int
    ruolo: str
    griglia: str | None
    sofascore_url: str | None


@dataclass(frozen=True)
class DatiPartita:
    partita_id: int
    data: datetime
    stagione: int
    casa_id: int
    trasferta_id: int
    nomi_squadre: dict[int, str]
    titolari: list[Titolare]
    storico: dict[int, list[RigaPresenza]]
    arbitro: StatArbitro | None
    medie: MedieCampionato
    contesto: ContestoInfo
    duelli_manuali: dict[int, int]


@dataclass(frozen=True)
class Fattore:
    nome: str
    valore: float
    motivazione: str | None
    n_dati: int


@dataclass(frozen=True)
class Candidato:
    giocatore_id: int
    nome: str
    squadra_id: int
    ruolo: str
    probabilita: float
    motivazioni: list[str]
    affidabilita: Literal["alto", "medio", "dati insufficienti"]
    avversario_diretto_id: int | None
    fattori: list[Fattore]
    quota: float | None
    prob_implicita: float | None
    valore: float | None
