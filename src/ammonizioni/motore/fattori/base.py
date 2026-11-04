import math

from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import Fattore, MedieCampionato, RigaPresenza

MOTIVAZIONE_RITARDO = "Tanti falli, pochi gialli: in ritardo"


def _tasso_e_ritardo(
    storico: list[RigaPresenza],
    ruolo: str,
    medie: MedieCampionato,
    stagione: int,
    pesi: Pesi,
) -> tuple[float, bool]:
    medie_ruolo = medie.per_ruolo[ruolo]

    # 1. gialli/90 per stagione (corrente, -1, -2); ultime 5 della corrente pesano di più
    corrente = sorted(
        (r for r in storico if r.stagione == stagione), key=lambda r: r.data
    )
    ultime5 = {id(r) for r in corrente[-5:]}
    tassi: list[tuple[float, float]] = []  # (peso stagione, gialli/90)
    for k, peso in enumerate(pesi.pesi_stagioni):
        minuti_p = gialli_p = 0.0
        for r in storico:
            if r.stagione != stagione - k:
                continue
            m = pesi.moltiplicatore_ultime5 if id(r) in ultime5 else 1.0
            minuti_p += r.minuti * m
            gialli_p += r.gialli * m
        if minuti_p > 0:
            tassi.append((peso, gialli_p / minuti_p * 90))
    minuti_tot = sum(r.minuti for r in storico)
    if tassi:
        somma_pesi = sum(p for p, _ in tassi)
        tasso = sum(p * t for p, t in tassi) / somma_pesi
    else:
        tasso = medie_ruolo.gialli90

    # 2. restringimento al ruolo
    tasso = (tasso * minuti_tot + medie_ruolo.gialli90 * pesi.minuti_prior) / (
        minuti_tot + pesi.minuti_prior
    )

    # 3. "in ritardo": tanti falli ma pochi gialli rispetto al ruolo
    in_ritardo = False
    if minuti_tot > 0:
        falli90 = sum(r.falli_commessi for r in storico) / minuti_tot * 90
        gialli90 = sum(r.gialli for r in storico) / minuti_tot * 90
        if (
            falli90 >= pesi.soglia_ritardo_falli * medie_ruolo.falli90
            and gialli90 < medie_ruolo.gialli90
        ):
            tasso *= pesi.bonus_ritardo
            in_ritardo = True
    return tasso, in_ritardo


def tasso_base90(
    storico: list[RigaPresenza],
    ruolo: str,
    medie: MedieCampionato,
    stagione: int,
    pesi: Pesi,
) -> float:
    """Gialli per 90 minuti dopo pesi stagionali, restringimento al ruolo e bonus "in ritardo"."""
    return _tasso_e_ritardo(storico, ruolo, medie, stagione, pesi)[0]


def _minuti_attesi(storico: list[RigaPresenza]) -> float:
    titolari = sorted((r for r in storico if r.titolare), key=lambda r: r.data, reverse=True)[:5]
    if not titolari:
        return 90.0
    return min(90.0, sum(r.minuti for r in titolari) / len(titolari))


def base_giocatore(
    storico: list[RigaPresenza],
    ruolo: str,
    medie: MedieCampionato,
    stagione: int,
    pesi: Pesi,
) -> Fattore:
    """Probabilità base di ammonizione del giocatore (il valore è una probabilità, non un moltiplicatore)."""
    tasso, in_ritardo = _tasso_e_ritardo(storico, ruolo, medie, stagione, pesi)
    p = 1 - math.exp(-tasso * _minuti_attesi(storico) / 90)
    return Fattore(
        nome="base",
        valore=p,
        motivazione=MOTIVAZIONE_RITARDO if in_ritardo else None,
        n_dati=sum(r.minuti for r in storico),
    )
