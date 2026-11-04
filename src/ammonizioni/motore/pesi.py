from dataclasses import asdict, dataclass, fields

from sqlalchemy.orm import Session

from ammonizioni.db.repo import leggi_impostazione, scrivi_impostazione

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
    # DA VERIFICARE sul regolamento Serie A in corso
    soglie_diffida: tuple[int, ...] = (4, 9, 13, 16, 19)
    attenuazione_pochi_dati: float = 0.2
    limiti_fattore: tuple[float, float] = (0.7, 1.6)
    limiti_probabilita: tuple[float, float] = (0.02, 0.70)


def carica_pesi(s: Session) -> Pesi:
    """Legge i pesi dalle impostazioni: chiavi mancanti -> default, chiavi sconosciute ignorate."""
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
    return Pesi(**valori)


def salva_pesi(s: Session, pesi: Pesi) -> None:
    scrivi_impostazione(s, CHIAVE_PESI, asdict(pesi))


def attenua(valore: float, n: int, soglia: int, pesi: Pesi) -> float:
    """Avvicina a 1 un fattore calcolato su pochi dati."""
    return 1 + (valore - 1) * (pesi.attenuazione_pochi_dati if n < soglia else 1)


def limita(valore: float, pesi: Pesi) -> float:
    basso, alto = pesi.limiti_fattore
    return max(basso, min(alto, valore))
