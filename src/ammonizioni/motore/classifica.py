import math

from ammonizioni.motore.fattori.base import base_giocatore, tasso_base90
from ammonizioni.motore.fattori.arbitro import fattore_arbitro
from ammonizioni.motore.fattori.contesto import fattore_contesto
from ammonizioni.motore.fattori.duello import avversario_diretto, fattore_duello
from ammonizioni.motore.fattori.situazione import fattore_situazione
from ammonizioni.motore.fattori.storia import fattore_storia
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import Candidato, DatiPartita, Fattore, StatArbitro

MINUTI_DATI_INSUFFICIENTI = 270
MINUTI_AFFIDABILE = 900
MAX_MOTIVAZIONI = 3


def converti_quota(testo: str) -> float:
    """Converte "2,10" o "2.10" in numero; la quota deve essere maggiore di 1."""
    errore = ValueError("Quota non valida: deve essere un numero maggiore di 1")
    try:
        quota = float(str(testo).strip().replace(",", "."))
    except ValueError:
        raise errore from None
    if not math.isfinite(quota) or quota <= 1:
        raise errore
    return quota


def affidabilita(base: Fattore, arbitro: StatArbitro | None, pesi: Pesi) -> str:
    if base.n_dati < MINUTI_DATI_INSUFFICIENTI:
        return "dati insufficienti"
    if (
        base.n_dati >= MINUTI_AFFIDABILE
        and arbitro is not None
        and arbitro.partite >= pesi.soglia_partite_arbitro
    ):
        return "alto"
    return "medio"


def _motivazioni(fattori: list[Fattore], pesi: Pesi) -> list[str]:
    candidate: list[tuple[float, str]] = []
    for f in fattori:
        if f.motivazione is None:
            continue
        if f.nome == "base":
            # il testo di base c'e' solo se "in ritardo": peso fisso del bonus
            forza = abs(math.log(pesi.bonus_ritardo))
        else:
            forza = abs(math.log(f.valore))
        candidate.append((forza, f.motivazione))
    candidate.sort(key=lambda c: -c[0])  # sort stabile: a parita' resta l'ordine dei fattori
    return [testo for _, testo in candidate[:MAX_MOTIVAZIONI]]


def classifica(
    dati: DatiPartita, pesi: Pesi, quote: dict[int, float] | None = None
) -> list[Candidato]:
    """Candidati (portieri esclusi) in ordine di probabilita' decrescente."""
    quote = quote or {}
    medie = dati.medie
    per_id = {t.giocatore_id: t for t in dati.titolari}
    basso, alto = pesi.limiti_probabilita
    risultato: list[Candidato] = []

    for t in dati.titolari:
        if t.ruolo == "G":
            continue
        ruolo = t.ruolo if t.ruolo in medie.per_ruolo else "M"
        storico = dati.storico.get(t.giocatore_id, [])
        compagni = [x for x in dati.titolari if x.squadra_id == t.squadra_id]
        avversari = [x for x in dati.titolari if x.squadra_id != t.squadra_id]
        avversario_squadra = dati.trasferta_id if t.squadra_id == dati.casa_id else dati.casa_id

        avv_id = avversario_diretto(
            t, avversari, dati.duelli_manuali.get(t.giocatore_id), compagni=compagni
        )
        avv = per_id.get(avv_id) if avv_id is not None else None
        if avv is None:
            avv_id = None
        storico_avv = dati.storico.get(avv_id, []) if avv_id is not None else []

        base = base_giocatore(storico, ruolo, medie, dati.stagione, pesi)
        duello = fattore_duello(avv, storico_avv, medie, pesi)
        arbitro = fattore_arbitro(dati.arbitro, t.squadra_id, medie, pesi)
        contesto = fattore_contesto(dati.contesto, t.squadra_id, medie, pesi)
        storia = fattore_storia(
            storico,
            avversario_squadra,
            dati.contesto.rivalita,
            storico_avv,
            tasso_base90(storico, ruolo, medie, dati.stagione, pesi),
            pesi,
            nome_avversario=dati.nomi_squadre.get(avversario_squadra, ""),
            nome_avv_diretto=avv.nome if avv else "",
        )
        situazione = fattore_situazione(storico, dati.stagione, pesi)
        fattori = [base, duello, arbitro, contesto, storia, situazione]

        p = base.valore
        for f in fattori[1:]:
            p *= f.valore
        p = max(basso, min(alto, p))

        quota = quote.get(t.giocatore_id)
        prob_implicita = 1 / quota if quota else None
        risultato.append(
            Candidato(
                giocatore_id=t.giocatore_id,
                nome=t.nome,
                squadra_id=t.squadra_id,
                ruolo=t.ruolo,
                probabilita=p,
                motivazioni=_motivazioni(fattori, pesi),
                affidabilita=affidabilita(base, dati.arbitro, pesi),
                avversario_diretto_id=avv_id,
                fattori=fattori,
                quota=quota if prob_implicita is not None else None,
                prob_implicita=prob_implicita,
                valore=p - prob_implicita if prob_implicita is not None else None,
            )
        )

    risultato.sort(key=lambda c: -c.probabilita)
    return risultato
