from ammonizioni.motore.pesi import Pesi, attenua, limita
from ammonizioni.motore.tipi import Fattore, MedieCampionato, StatArbitro, decimale

SOGLIA_MOTIVAZIONE = 1.05
SOGLIA_PARTITE_CON_SQUADRA = 2


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
    con = arbitro.gialli_medi_con.get(squadra_id)
    if con is not None and arbitro.gialli_medi > 0:
        gialli_con, n_con = con
        if n_con >= SOGLIA_PARTITE_CON_SQUADRA:
            grezzo *= attenua(
                gialli_con / arbitro.gialli_medi, n_con, SOGLIA_PARTITE_CON_SQUADRA, pesi
            )
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
