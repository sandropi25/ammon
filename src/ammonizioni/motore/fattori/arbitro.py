from ammonizioni.motore.pesi import Pesi, attenua, limita
from ammonizioni.motore.tipi import Fattore, MedieCampionato, StatArbitro, decimale

SOGLIA_MOTIVAZIONE = 1.05
SOGLIA_PARTITE_CON_SQUADRA = 2
# Restringimento di "arbitro con questa squadra": il rapporto (gialli con la squadra /
# gialli medi dell'arbitro) conta per n / (n + PRIOR) e per il resto vale 1. Prima contava
# pieno già con 2 partite (2 partite da 7 gialli = +30%); ora con 2 partite conta per 2/10,
# con 8 per metà, con 24 per tre quarti.
PRIOR_PARTITE_CON_SQUADRA = 8


def inclinazione_con_squadra(arbitro: StatArbitro | None, squadra_id: int) -> float:
    """Moltiplicatore "arbitro con questa squadra" ristretto verso 1 (1 = nessun effetto):
    almeno 2 partite con la squadra, poi peso n / (n + PRIOR_PARTITE_CON_SQUADRA)."""
    if arbitro is None or arbitro.gialli_medi <= 0:
        return 1.0
    con = arbitro.gialli_medi_con.get(squadra_id)
    if con is None:
        return 1.0
    gialli_con, n_con = con
    if n_con < SOGLIA_PARTITE_CON_SQUADRA:
        return 1.0
    peso = n_con / (n_con + PRIOR_PARTITE_CON_SQUADRA)
    return 1 + (gialli_con / arbitro.gialli_medi - 1) * peso


def fattore_arbitro(
    arbitro: StatArbitro | None,
    squadra_id: int,
    medie: MedieCampionato,
    pesi: Pesi,
) -> Fattore:
    """Quanto l'arbitro ammonisce rispetto alla media del campionato."""
    if arbitro is None:
        return Fattore("arbitro", 1.0, None, 0)

    grezzo = (
        1
        + pesi.coeff_gialli_arbitro * (arbitro.gialli_medi / medie.gialli_partita - 1)
        + pesi.coeff_falli_arbitro * (arbitro.falli_medi / medie.falli_partita - 1)
    )
    grezzo *= inclinazione_con_squadra(arbitro, squadra_id)
    valore = limita(attenua(grezzo, arbitro.partite, pesi.soglia_partite_arbitro, pesi), pesi)

    motivazione = None
    if valore >= SOGLIA_MOTIVAZIONE:
        motivazione = f"arbitro da {decimale(arbitro.gialli_medi)} gialli"
    elif (
        arbitro.falli_medi > medie.falli_partita
        and arbitro.gialli_medi < medie.gialli_partita
    ):
        motivazione = "arbitro: tanti falli, pochi gialli"
    return Fattore("arbitro", valore, motivazione, arbitro.partite)
