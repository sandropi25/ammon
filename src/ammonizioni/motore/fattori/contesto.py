from ammonizioni.motore.pesi import Pesi, attenua, limita
from ammonizioni.motore.tipi import ContestoInfo, Fattore, MedieCampionato

SOGLIA_MOTIVAZIONE = 1.05
SOGLIA_PRECEDENTI = 3
PARTITE_MINIME_POSTA = 19
MARGINE_PUNTI_POSTA = 3

_ARTICOLO_POSTA = {"titolo": "il", "Europa": "l'", "salvezza": "la"}
# (posta, posizioni in classifica da controllare), nell'ordine di priorita'
_SOGLIE_POSTA = (("titolo", (1,)), ("Europa", (4, 6)), ("salvezza", (17,)))


def _testo_posta(posta: str) -> str:
    articolo = _ARTICOLO_POSTA.get(posta, "il")
    separatore = "" if articolo.endswith("'") else " "
    return f"In lotta per {articolo}{separatore}{posta}"


def fattore_contesto(
    ctx: ContestoInfo,
    squadra_id: int,
    medie: MedieCampionato,
    pesi: Pesi,
) -> Fattore:
    """Derby, campo caldo, posta in palio e precedenti nervosi."""
    valore = 1.0
    motivazioni: list[str] = []
    if ctx.rivalita:
        valore *= pesi.rivalita
        motivazioni.append("Derby/rivalità")
    if ctx.campo_caldo:
        valore *= pesi.campo_caldo
        motivazioni.append("Campo caldo")
    posta = ctx.posta.get(squadra_id)
    if posta:
        valore *= pesi.posta
        motivazioni.append(_testo_posta(posta))

    precedenti = 1.0
    if ctx.precedenti_gialli_medi is not None:
        grezzo = 1 + pesi.coeff_precedenti * (
            ctx.precedenti_gialli_medi / medie.gialli_partita - 1
        )
        precedenti = attenua(grezzo, ctx.precedenti_n, SOGLIA_PRECEDENTI, pesi)
    valore *= precedenti
    if precedenti >= SOGLIA_MOTIVAZIONE:
        motivazioni.append("Precedenti nervosi")

    return Fattore(
        "contesto",
        limita(valore, pesi),
        " · ".join(motivazioni) if motivazioni else None,
        ctx.precedenti_n,
    )


def posta_in_classifica(
    partite_giocate: list[tuple[int, int, int, int]], squadra_id: int
) -> str | None:
    """"titolo" / "Europa" / "salvezza" se la squadra e' entro 3 punti dalla posizione soglia.

    Serve almeno 19 partite giocate dalla squadra; None altrimenti o se la squadra non
    compare nella classifica. Parita' di punti: differenza reti, gol fatti, id squadra.
    """
    punti: dict[int, int] = {}
    diff: dict[int, int] = {}
    fatti: dict[int, int] = {}
    giocate: dict[int, int] = {}
    for casa, trasferta, gc, gt in partite_giocate:
        for sq, gf, gs in ((casa, gc, gt), (trasferta, gt, gc)):
            giocate[sq] = giocate.get(sq, 0) + 1
            diff[sq] = diff.get(sq, 0) + gf - gs
            fatti[sq] = fatti.get(sq, 0) + gf
            punti[sq] = punti.get(sq, 0) + (3 if gf > gs else 1 if gf == gs else 0)

    if squadra_id not in giocate or giocate[squadra_id] < PARTITE_MINIME_POSTA:
        return None
    ordine = sorted(punti, key=lambda sq: (-punti[sq], -diff[sq], -fatti[sq], sq))
    mio = punti[squadra_id]
    for posta, posizioni in _SOGLIE_POSTA:
        for pos in posizioni:
            if pos > len(ordine):
                continue
            if abs(mio - punti[ordine[pos - 1]]) <= MARGINE_PUNTI_POSTA:
                return posta
    return None
