from ammonizioni.config import SERIE_A, SOGLIE_DIFFIDA
from ammonizioni.motore.pesi import Pesi, limita
from ammonizioni.motore.tipi import Fattore, RigaPresenza

ULTIME_DA_TITOLARE = 5


def _soglie_diffida(campionato_id: int, pesi: Pesi) -> tuple[int, ...]:
    """Soglie di diffida del campionato. La Serie A usa quelle dei pesi (modificabili da
    Impostazioni); gli altri campionati quelle di `SOGLIE_DIFFIDA`."""
    if campionato_id == SERIE_A:
        return pesi.soglie_diffida
    return SOGLIE_DIFFIDA.get(campionato_id, pesi.soglie_diffida)


def fattore_situazione(
    storico: list[RigaPresenza], stagione: int, pesi: Pesi, campionato_id: int = SERIE_A
) -> Fattore:
    """Diffida (gialli nel campionato della partita nella stagione) e rischio di uscire presto.
    Contano solo i gialli del campionato: coppe e altri campionati hanno conteggi a parte."""
    campionato = [
        r for r in storico if r.stagione == stagione and r.competizione_id == campionato_id
    ]
    valore = 1.0
    motivazioni: list[str] = []

    if sum(r.gialli for r in campionato) in _soglie_diffida(campionato_id, pesi):
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
        len(campionato),
    )
