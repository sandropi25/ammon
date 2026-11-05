import logging
from dataclasses import asdict, dataclass, fields

from sqlalchemy.orm import Session

from ammonizioni.db.repo import leggi_impostazione, scrivi_impostazione

log = logging.getLogger(__name__)

CHIAVE_PESI = "pesi"


@dataclass(frozen=True)
class Pesi:
    pesi_stagioni: tuple[float, float, float] = (0.6, 0.3, 0.1)
    moltiplicatore_ultime5: float = 2.0
    minuti_prior: float = 900
    soglia_ritardo_falli: float = 1.3
    bonus_ritardo: float = 1.10
    coeff_falli_subiti: float = 0.25
    coeff_dribbling: float = 0.15
    coeff_forma: float = 0.10
    coeff_gialli_arbitro: float = 1.0
    coeff_falli_arbitro: float = 0.2
    soglia_partite_arbitro: int = 5
    rivalita: float = 1.20
    campo_caldo: float = 1.08
    posta: float = 1.07
    coeff_precedenti: float = 0.3
    coeff_storia: float = 0.3
    soglia_precedenti: int = 2
    diffidato: float = 0.85
    sostituzione: float = 0.90
    minuti_sostituzione: int = 60
    # Soglie di diffida della Serie A (la Liga usa config.SOGLIE_DIFFIDA).
    # DA VERIFICARE sul regolamento Serie A in corso
    soglie_diffida: tuple[int, ...] = (4, 9, 13, 16, 19)
    attenuazione_pochi_dati: float = 0.2
    limiti_fattore: tuple[float, float] = (0.7, 1.6)
    limiti_probabilita: tuple[float, float] = (0.02, 0.70)


# fattori moltiplicativi: con 0 la probabilita' si azzera e il logaritmo delle motivazioni fallisce
FATTORI_MOLTIPLICATIVI = (
    "bonus_ritardo", "rivalita", "campo_caldo", "posta", "diffidato", "sostituzione",
)
SOGLIE_MINIME_UNO = ("soglia_partite_arbitro", "soglia_precedenti")


def valida_pesi(pesi: Pesi) -> None:
    """ValueError (messaggio italiano col nome del campo) per i valori che bloccano il motore.
    I coefficienti (coeff_*) possono restare >= 0."""
    if not pesi.minuti_prior > 0:
        raise ValueError("minuti_prior: deve essere maggiore di 0")
    for nome in FATTORI_MOLTIPLICATIVI:
        if not getattr(pesi, nome) > 0:
            raise ValueError(f"{nome}: deve essere maggiore di 0")
    for nome in SOGLIE_MINIME_UNO:
        if not getattr(pesi, nome) >= 1:
            raise ValueError(f"{nome}: deve essere almeno 1")
    stagioni = pesi.pesi_stagioni
    if len(stagioni) != 3:
        raise ValueError("pesi_stagioni: servono esattamente 3 valori")
    if any(not p >= 0 for p in stagioni) or not sum(stagioni) > 0:
        raise ValueError("pesi_stagioni: valori non negativi con somma maggiore di 0")
    for nome in ("limiti_fattore", "limiti_probabilita"):
        if len(getattr(pesi, nome)) != 2:
            raise ValueError(f"{nome}: servono esattamente 2 valori")
    basso, alto = pesi.limiti_fattore
    if not 0 < basso < alto:
        raise ValueError("limiti_fattore: servono due valori con 0 < minimo < massimo")
    basso, alto = pesi.limiti_probabilita
    if not 0 < basso < alto < 1:
        raise ValueError("limiti_probabilita: servono due probabilità con 0 < minimo < massimo < 1")


def carica_pesi(s: Session) -> Pesi:
    """Legge i pesi dalle impostazioni: chiavi mancanti -> default, chiavi sconosciute ignorate.
    Valori salvati non validi -> tutti i default (con un avviso nel log): un valore sbagliato
    nel database non deve mai bloccare il motore."""
    salvati = leggi_impostazione(s, CHIAVE_PESI, None)
    if not isinstance(salvati, dict):
        return Pesi()
    default = Pesi()
    valori = {}
    for campo in fields(Pesi):
        if campo.name not in salvati:
            continue
        v = salvati[campo.name]
        if isinstance(getattr(default, campo.name), tuple) and isinstance(v, list):
            v = tuple(v)
        valori[campo.name] = v
    try:
        pesi = Pesi(**valori)
        valida_pesi(pesi)
    except (TypeError, ValueError) as errore:
        log.warning("Pesi salvati non validi (%s): uso i valori predefiniti", errore)
        return default
    return pesi


def salva_pesi(s: Session, pesi: Pesi) -> None:
    scrivi_impostazione(s, CHIAVE_PESI, asdict(pesi))


def attenua(valore: float, n: int, soglia: int, pesi: Pesi) -> float:
    """Avvicina a 1 un fattore calcolato su pochi dati."""
    return 1 + (valore - 1) * (pesi.attenuazione_pochi_dati if n < soglia else 1)


def limita(valore: float, pesi: Pesi) -> float:
    basso, alto = pesi.limiti_fattore
    return max(basso, min(alto, valore))
