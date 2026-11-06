from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ammonizioni.config import SERIE_A

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
    dribbling90: float  # 0 = la lega non ha il dato (fonte senza dribbling)
    ga90: float
    voto: float | None  # None = la lega non ha voti (fonte senza voto)


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
    # punti per partita in campionato (solo squadre con almeno 3 partite): serve a capire
    # quale squadra è sfavorita quando mancano le quote 1X2
    punti_partita: dict[int, float] = field(default_factory=dict)


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
    campionato_id: int = SERIE_A  # il campionato della partita: medie, posta e diffide sono suoi
    # probabili subentranti (vuota se non richiesta o non nota) e loro contorno
    panchina: list[Titolare] = field(default_factory=list)
    tendenza_cambi: dict[int, dict[str, float]] = field(default_factory=dict)  # squadra -> ruolo -> quota
    prob_vittoria: dict[int, float] = field(default_factory=dict)  # dalle quote 1X2 ESPN
    formazioni_ufficiali: bool = False  # solo per l'affidabilità: titolari ufficiali o probabili


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
    subentro: "InfoSubentro | None" = None  # solo per i probabili subentranti
    # affidabilità 0-100 (vedi motore.affidabilita) e i suoi motivi in chiaro; il campo
    # `affidabilita` sopra ne è ricavato. Non influisce sulla probabilità.
    affidabilita_punti: int = 0
    affidabilita_motivi: tuple[str, ...] = ()

    @property
    def subentrante(self) -> bool:
        return self.subentro is not None


@dataclass(frozen=True)
class InfoSubentro:
    """Perché un panchinaro è candidato: quanto entra, quanto gioca, al posto di chi."""
    probabilita_ingresso: float
    minuti_medi: float
    panchine: int
    ingressi: int
    al_posto_di_id: int | None
    al_posto_di_nome: str | None
    gialli90: float | None  # None: meno di 90 minuti nei dati
    falli90: float | None
    media_gialli90: float  # del ruolo nel campionato
    media_falli90: float
    sopra_media: bool  # solo un'evidenza: non filtra
    sfavorita: bool
