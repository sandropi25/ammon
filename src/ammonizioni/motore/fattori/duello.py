from ammonizioni.motore.pesi import Pesi, attenua, limita
from ammonizioni.motore.tipi import (
    Fattore,
    MedieCampionato,
    RigaPresenza,
    Titolare,
    decimale,
)

SOGLIA_MOTIVAZIONE = 1.05
SOGLIA_PARTITE_ATTENUAZIONE = 5
ULTIME_PER_FORMA = 5
ULTIME_PER_GOL = 3

_LINEA_OPPOSTA = {"D": "F", "F": "D", "M": "M"}


def _posizione(griglia: str | None) -> tuple[int, int] | None:
    """Da "riga:colonna" a (riga, colonna); None se assente o malformata."""
    if not griglia:
        return None
    try:
        riga_s, colonna_s = griglia.split(":")
        return int(riga_s), int(colonna_s)
    except ValueError:
        return None


def _corsie(squadra: list[Titolare]) -> dict[int, float]:
    """Corsia normalizzata in [0, 1] di ogni titolare con griglia, nella propria riga.

    Un giocatore solo nella riga ha corsia 0,5.
    """
    posizioni = {
        t.giocatore_id: p for t in squadra if (p := _posizione(t.griglia)) is not None
    }
    per_riga: dict[int, int] = {}
    for riga_g, _ in posizioni.values():
        per_riga[riga_g] = per_riga.get(riga_g, 0) + 1
    return {
        gid: 0.5 if per_riga[riga_g] == 1 else (colonna - 1) / (per_riga[riga_g] - 1)
        for gid, (riga_g, colonna) in posizioni.items()
    }


def avversario_diretto(
    giocatore: Titolare,
    avversari: list[Titolare],
    manuale: int | None,
    compagni: list[Titolare] | None = None,
) -> int | None:
    """Id dell'avversario che marca `giocatore`: quello manuale, altrimenti dalla griglia.

    `compagni` e' la formazione della squadra del giocatore (serve a contare quanti
    stanno nella sua stessa riga); se manca, il giocatore e' considerato solo nella riga.
    """
    if manuale is not None:
        return manuale
    linea = _LINEA_OPPOSTA.get(giocatore.ruolo)
    if linea is None or _posizione(giocatore.griglia) is None:
        return None
    squadra = [t for t in (compagni or []) if t.giocatore_id != giocatore.giocatore_id]
    corsia = _corsie(squadra + [giocatore])[giocatore.giocatore_id]

    corsie_avv = _corsie(avversari)
    for linea_cercata in (linea, "M"):
        candidati = [
            t for t in avversari if t.ruolo == linea_cercata and t.giocatore_id in corsie_avv
        ]
        if candidati:
            break
    else:
        return None
    specchio = 1 - corsia
    scelto = min(
        candidati,
        key=lambda t: (round(abs(corsie_avv[t.giocatore_id] - specchio), 9), t.giocatore_id),
    )
    return scelto.giocatore_id


def _per90(righe: list[RigaPresenza], stat: str) -> float | None:
    minuti = sum(r.minuti for r in righe)
    if minuti <= 0:
        return None
    return sum(getattr(r, stat) for r in righe) / minuti * 90


def _rapporto(valore: float | None, media: float) -> float:
    """valore/media, neutro (1) se manca il dato o la media e' nulla."""
    if valore is None or media <= 0:
        return 1.0
    return valore / media


def _voto_medio(righe: list[RigaPresenza]) -> float | None:
    voti = [r.voto for r in righe if r.voto is not None]
    return sum(voti) / len(voti) if voti else None


def _scarto_forma(recente: float | None, stagione: float | None) -> float:
    """recente/stagione - 1, limitato a [-1, 1]; 0 se non calcolabile."""
    if recente is None or stagione is None or stagione <= 0:
        return 0.0
    return max(-1.0, min(1.0, recente / stagione - 1))


def _forma(ordinate: list[RigaPresenza]) -> float:
    """Media degli scarti di gol+assist/90 e voto (ultime 5 contro stagione piu' recente)."""
    if not ordinate:
        return 0.0
    ultima_stagione = max(r.stagione for r in ordinate)
    stagione = [r for r in ordinate if r.stagione == ultima_stagione]
    ultime5 = ordinate[-ULTIME_PER_FORMA:]

    def ga90(righe):
        minuti = sum(r.minuti for r in righe)
        return sum(r.gol + r.assist for r in righe) / minuti * 90 if minuti > 0 else None

    scarto_ga = _scarto_forma(ga90(ultime5), ga90(stagione))
    scarto_voto = _scarto_forma(_voto_medio(ultime5), _voto_medio(stagione))
    return (scarto_ga + scarto_voto) / 2


def fattore_duello(
    avversario: Titolare | None,
    storico_avv: list[RigaPresenza],
    medie: MedieCampionato,
    pesi: Pesi,
) -> Fattore:
    """Quanto l'avversario diretto induce al fallo (falli subiti, dribbling, forma)."""
    if avversario is None:
        return Fattore("duello", 1.0, None, 0)

    ordinate = sorted(storico_avv, key=lambda r: r.data)
    minuti = sum(r.minuti for r in ordinate)
    media = medie.per_ruolo[avversario.ruolo]
    fs90 = _per90(ordinate, "falli_subiti")
    rapporto_fs = _rapporto(fs90, media.falli_subiti90)
    rapporto_drib = _rapporto(_per90(ordinate, "dribbling_tentati"), media.dribbling90)

    grezzo = (
        1
        + pesi.coeff_falli_subiti * (rapporto_fs - 1)
        + pesi.coeff_dribbling * (rapporto_drib - 1)
        + pesi.coeff_forma * _forma(ordinate)
    )
    n = minuti / 90
    valore = limita(attenua(grezzo, n, SOGLIA_PARTITE_ATTENUAZIONE, pesi), pesi)

    motivazione = None
    if valore >= SOGLIA_MOTIVAZIONE:
        ultime = ordinate[-ULTIME_PER_GOL:]
        gol = sum(r.gol for r in ultime)
        if gol > 0:
            motivazione = f"marca {avversario.nome}, {gol} gol nelle ultime {len(ultime)}"
        else:
            motivazione = (
                f"marca {avversario.nome}, {decimale(fs90 or 0.0)} falli subiti a partita"
            )
    return Fattore("duello", valore, motivazione, round(n))
