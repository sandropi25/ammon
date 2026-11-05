from ammonizioni.motore.pesi import Pesi, attenua, limita
from ammonizioni.motore.tipi import Fattore, RigaPresenza

SOGLIA_PARTITE_MOTIVAZIONE = 2
MIN_DERBY_CONSECUTIVI = 2


def _partite(righe: list[RigaPresenza]) -> int:
    return len({r.partita_id for r in righe})


def _fattore_sottoinsieme(
    righe: list[RigaPresenza], tasso_base90: float, pesi: Pesi
) -> float | None:
    """Fattore del sottoinsieme; None se vuoto o senza minuti."""
    minuti = sum(r.minuti for r in righe)
    if not righe or minuti <= 0:
        return None
    r = sum(x.gialli for x in righe) / minuti * 90 / tasso_base90
    grezzo = 1 + pesi.coeff_storia * (r - 1)
    return attenua(grezzo, _partite(righe), pesi.soglia_precedenti, pesi)


def _derby_consecutivi(righe: list[RigaPresenza]) -> int:
    """Quanti derby piu' recenti consecutivi con almeno un giallo."""
    k = 0
    for r in sorted(righe, key=lambda x: x.data, reverse=True):
        if r.gialli < 1:
            break
        k += 1
    return k


def fattore_storia(
    storico: list[RigaPresenza],
    avversario_squadra_id: int,
    oggi_rivalita: bool,
    storico_avv_diretto: list[RigaPresenza],
    tasso_base90: float,
    pesi: Pesi,
    *,
    nome_avversario: str = "",
    nome_avv_diretto: str = "",
) -> Fattore:
    """Storico personale del giocatore contro l'avversario, nei derby e contro l'avversario diretto."""
    if tasso_base90 <= 0:
        return Fattore("storia", 1.0, None, 0)

    # un giallo preso dalla panchina (0 minuti) conta: aggiunge il giallo e nessun minuto
    giocate = [r for r in storico if r.minuti > 0 or r.gialli > 0]
    squadre_diretto: dict[int, set[int]] = {}
    for r in storico_avv_diretto:
        if r.minuti <= 0:
            continue
        squadre_diretto.setdefault(r.partita_id, set()).add(r.squadra_id)

    a = [r for r in giocate if r.avversario_id == avversario_squadra_id]
    b = [r for r in giocate if r.rivalita] if oggi_rivalita else []
    c = [
        r
        for r in giocate
        if r.minuti > 0  # un cartellino dalla panchina non e' un duello
        and any(s != r.squadra_id for s in squadre_diretto.get(r.partita_id, ()))
    ]

    valore = 1.0
    qualificati: list[tuple[float, str, list[RigaPresenza]]] = []
    for chiave, righe in (("b", b), ("a", a), ("c", c)):
        f = _fattore_sottoinsieme(righe, tasso_base90, pesi)
        if f is None:
            continue
        valore *= f
        if _partite(righe) >= SOGLIA_PARTITE_MOTIVAZIONE:
            qualificati.append((f, chiave, righe))

    motivazione = None
    # il piu' forte per primo; a parita' resta l'ordine b, a, c (sort stabile)
    for f, chiave, righe in sorted(qualificati, key=lambda t: -t[0]):
        if chiave == "b":
            k = _derby_consecutivi(righe)
            if k >= MIN_DERBY_CONSECUTIVI:
                motivazione = f"Ammonito negli ultimi {k} derby"
                break
        elif chiave == "a":
            gialli = sum(r.gialli for r in righe)
            if gialli >= 1 and f > 1:
                parola = "giallo" if gialli == 1 else "gialli"
                motivazione = (
                    f"{gialli} {parola} in {_partite(righe)} partite contro {nome_avversario}"
                )
                break
        elif any(r.gialli >= 1 for r in righe):
            motivazione = f"già ammonito contro {nome_avv_diretto}"
            break

    unione = {r.partita_id for righe in (a, b, c) for r in righe}
    return Fattore("storia", limita(valore, pesi), motivazione, len(unione))
