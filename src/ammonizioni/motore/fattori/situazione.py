from ammonizioni.motore.pesi import Pesi, limita
from ammonizioni.motore.tipi import Fattore, RigaPresenza

SERIE_A = 135
ULTIME_DA_TITOLARE = 5


def fattore_situazione(storico: list[RigaPresenza], stagione: int, pesi: Pesi) -> Fattore:
    """Diffida (gialli in Serie A nella stagione) e rischio di uscire presto."""
    serie_a = [
        r for r in storico if r.stagione == stagione and r.competizione_id == SERIE_A
    ]
    valore = 1.0
    motivazioni: list[str] = []

    if sum(r.gialli for r in serie_a) in pesi.soglie_diffida:
        valore *= pesi.diffidato
        motivazioni.append("Diffidato")

    titolari = sorted((r for r in storico if r.titolare), key=lambda r: r.data)
    ultime = titolari[-ULTIME_DA_TITOLARE:]
    if ultime and sum(r.minuti for r in ultime) / len(ultime) < pesi.minuti_sostituzione:
        valore *= pesi.sostituzione
        motivazioni.append("Spesso sostituito presto")

    return Fattore(
        "situazione",
        limita(valore, pesi),
        " · ".join(motivazioni) if motivazioni else None,
        len(serie_a),
    )
