"""Probabili subentranti: quanto spesso un panchinaro entra e quanti minuti gioca, la
tendenza dei cambi della squadra per ruolo e se la squadra è sfavorita (deve rincorrere)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ammonizioni.db.modelli import Giocatore, Partita, Presenza
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import RUOLI, DatiPartita, RigaPresenza, Titolare

PANCHINE_RECENTI = 15  # ultime partite in distinta da panchinaro
PANCHINE_PRIOR = 8  # restringimento verso la media del ruolo
# quota di panchinari che entrano, per ruolo (il terzo portiere non entra quasi mai)
PROB_INGRESSO_RUOLO = {"G": 0.03, "D": 0.35, "M": 0.45, "F": 0.5}
MINUTI_SUBENTRO_PREDEFINITI = 20.0
SOGLIA_INGRESSO = 0.15  # sotto non si mostra (decisione dell'utente)
# mai entrato in almeno 5 panchine: "non entra quasi mai", fuori anche se il restringimento
# verso la media del ruolo (con pochi dati) lo porterebbe sopra 0,15
PANCHINE_SENZA_INGRESSI = 5


def non_entra_mai(profilo: "ProfiloSubentro") -> bool:
    return profilo.ingressi == 0 and profilo.panchine >= PANCHINE_SENZA_INGRESSI
PARTITE_TENDENZA = 10
MARGINE_PROB_SFAVORITA = 0.10  # quote 1X2: vittoria meno probabile di almeno 10 punti
MARGINE_PUNTI_SFAVORITA = 0.5  # classifica: almeno mezzo punto a partita in meno
PARTITE_TITOLARE_CAMBIO = 10
MINUTI_SOSTITUITO = 80  # titolare uscito prima: sostituito


@dataclass(frozen=True)
class ProfiloSubentro:
    giocatore_id: int
    panchine: int
    ingressi: int
    minuti_medi: float
    ruolo: str
    probabilita_ingresso: float


def profilo_subentro(
    giocatore_id: int, ruolo: str, storico: list[RigaPresenza]
) -> ProfiloSubentro | None:
    """Profilo sulle ultime 15 partite in distinta da panchinaro (titolare False). Chi entra
    anche 1 minuto conta come ingresso. None senza nessuna panchina nei dati."""
    panchine = sorted((r for r in storico if not r.titolare), key=lambda r: r.data)
    panchine = panchine[-PANCHINE_RECENTI:]
    if not panchine:
        return None
    ingressi = [r for r in panchine if r.minuti > 0]
    minuti_medi = (
        sum(min(r.minuti, 90) for r in ingressi) / len(ingressi)
        if ingressi else MINUTI_SUBENTRO_PREDEFINITI
    )
    prior = PROB_INGRESSO_RUOLO.get(ruolo, PROB_INGRESSO_RUOLO["M"])
    probabilita = (len(ingressi) + prior * PANCHINE_PRIOR) / (len(panchine) + PANCHINE_PRIOR)
    return ProfiloSubentro(
        giocatore_id=giocatore_id,
        panchine=len(panchine),
        ingressi=len(ingressi),
        minuti_medi=minuti_medi,
        ruolo=ruolo,
        probabilita_ingresso=probabilita,
    )


def _ruolo(ruolo: str | None) -> str:
    return ruolo if ruolo in RUOLI else "M"


def tendenze_cambi(
    s: Session, squadre: list[int], prima_di: datetime, stagione: int
) -> dict[int, dict[str, float]]:
    """Per squadra, quota dei subentri (entrati almeno 1 minuto) per ruolo nelle ultime 10
    partite con statistiche (stagione corrente e precedente). Due query per tutte le squadre.
    Squadra senza subentri nei dati: dizionario vuoto."""
    risultato: dict[int, dict[str, float]] = {sq: {} for sq in squadre}
    if not squadre:
        return risultato
    righe = s.execute(
        select(Presenza.squadra_id, Presenza.partita_id, Partita.data_utc)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.squadra_id.in_(squadre),
            Partita.statistiche_scaricate.is_(True),
            Partita.data_utc < prima_di,
            Partita.stagione.in_((stagione, stagione - 1)),
        )
        .distinct()
    ).all()
    per_squadra: dict[int, list[tuple[datetime, int]]] = {}
    for sq, pid, data in righe:
        per_squadra.setdefault(sq, []).append((data, pid))
    scelte = {
        sq: {pid for _, pid in sorted(lista, reverse=True)[:PARTITE_TENDENZA]}
        for sq, lista in per_squadra.items()
    }
    ids = set().union(*scelte.values()) if scelte else set()
    if not ids:
        return risultato
    ingressi = s.execute(
        select(
            Presenza.squadra_id,
            Presenza.partita_id,
            func.coalesce(Presenza.ruolo, Giocatore.ruolo),
        )
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(
            Presenza.partita_id.in_(ids),
            Presenza.squadra_id.in_(squadre),
            Presenza.titolare.is_(False),
            Presenza.minuti > 0,
        )
    ).all()
    conteggi: dict[int, Counter] = {}
    for sq, pid, ruolo in ingressi:
        if pid in scelte.get(sq, set()):
            conteggi.setdefault(sq, Counter())[_ruolo(ruolo)] += 1
    for sq, conta in conteggi.items():
        totale = sum(conta.values())
        risultato[sq] = {r: conta[r] / totale for r in RUOLI if conta[r]}
    return risultato


def tendenza_cambi(
    s: Session, squadra_id: int, prima_di: datetime, stagione: int
) -> dict[str, float]:
    """Quota dei subentri per ruolo di una squadra (vedi `tendenze_cambi`)."""
    return tendenze_cambi(s, [squadra_id], prima_di, stagione)[squadra_id]


def sfavorita(dati: DatiPartita, squadra_id: int) -> bool:
    """Squadra sfavorita: con le quote 1X2 la sua vittoria è meno probabile di quella
    dell'avversaria di almeno 0,10; senza quote, ha almeno 0,5 punti a partita in meno."""
    avversaria = dati.trasferta_id if squadra_id == dati.casa_id else dati.casa_id
    prob = dati.prob_vittoria
    if squadra_id in prob and avversaria in prob:
        return prob[avversaria] - prob[squadra_id] >= MARGINE_PROB_SFAVORITA - 1e-9
    punti = dati.contesto.punti_partita
    if squadra_id in punti and avversaria in punti:
        return punti[avversaria] - punti[squadra_id] >= MARGINE_PUNTI_SFAVORITA - 1e-9
    return False


def fattori_tendenza(quote: dict[str, float], e_sfavorita: bool, pesi: Pesi) -> dict[str, float]:
    """Moltiplicatore della probabilità di ingresso per ruolo. Neutro (1) se la squadra non è
    sfavorita; se lo è, le quote dei subentri si ripesano (attaccanti ×1,2, difensori ×0,8,
    dai Pesi), si rinormalizzano e il fattore è quota ripesata / quota abituale."""
    neutri = {r: 1.0 for r in RUOLI}
    if not e_sfavorita or not quote:
        return neutri
    peso = {"F": pesi.cambi_attaccanti_sfavorita, "D": pesi.cambi_difensori_sfavorita}
    pesate = {r: q * peso.get(r, 1.0) for r, q in quote.items()}
    totale = sum(pesate.values())
    if totale <= 0:
        return neutri
    for r, q in quote.items():
        if q > 0:
            neutri[r] = (pesate[r] / totale) / q
    return neutri


def titolare_da_sostituire(
    panchinaro: Titolare, titolari: list[Titolare], storico: dict[int, list[RigaPresenza]]
) -> Titolare | None:
    """Titolare della stessa squadra e dello stesso ruolo sostituito più spesso: minuti medi
    da titolare (ultime 10) più bassi, fra chi è uscito prima dell'80' almeno una volta senza
    espulsione. None se nessuno di quel ruolo viene sostituito."""
    migliori: list[tuple[float, int, Titolare]] = []
    for t in titolari:
        if t.squadra_id != panchinaro.squadra_id or t.ruolo != panchinaro.ruolo:
            continue
        partenze = sorted(
            (r for r in storico.get(t.giocatore_id, []) if r.titolare), key=lambda r: r.data
        )[-PARTITE_TITOLARE_CAMBIO:]
        if not any(r.minuti < MINUTI_SOSTITUITO and r.rossi == 0 for r in partenze):
            continue
        media = sum(r.minuti for r in partenze) / len(partenze)
        migliori.append((media, t.giocatore_id, t))
    return min(migliori, key=lambda m: (m[0], m[1]))[2] if migliori else None
