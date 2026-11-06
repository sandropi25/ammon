"""Affidabilità di un candidato: un punteggio 0-100 su quanto i dati dietro la probabilità
sono solidi. NON cambia la probabilità: dice solo quanto fidarsi di quel numero.

Punti (totale 100): minuti nelle 3 stagioni 30 · costanza dei gialli 15 · formazione 15 ·
arbitro 12 · avversario diretto 10 · precedenti con l'avversaria 8 · attività recente 10.
Per i subentranti i 30 punti dei minuti si dividono in 10 (minuti) + 20 (panchine recenti) e i
10 dell'avversario diretto (che non si conosce) diventano "tendenza dei cambi della squadra
nota"."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ammonizioni.motore.tipi import InfoSubentro, RigaPresenza, StatArbitro

SOGLIA_ALTA = 70
SOGLIA_MEDIA = 40

MINUTI_PIENI = 2700  # 3 stagioni complete da titolare
MINUTI_PIENI_SUBENTRANTE = 900
PANCHINE_PIENE = 10
PARTITE_CON_GIALLO_PIENE = 6
PARTITE_ARBITRO_PIENE = 30
PRECEDENTI_PIENI = 4
PARTITE_RECENTI_PIENE = 4
GIORNI_RECENTI = 60

# avversario diretto
CERTO, PROBABILE, INCERTO = "certo", "probabile", "incerto"


@dataclass(frozen=True)
class Affidabilita:
    punti: int
    motivi: tuple[str, ...]

    @property
    def livello(self) -> str:
        return livello(self.punti)


def livello(punti: int) -> str:
    """"alta" (70 o più), "media" (40-69), "bassa" (sotto 40)."""
    if punti >= SOGLIA_ALTA:
        return "alta"
    if punti >= SOGLIA_MEDIA:
        return "media"
    return "bassa"


def vecchia_etichetta(punti: int) -> str:
    """Il vecchio campo `affidabilita` dei candidati, ricavato dal punteggio."""
    return {"alta": "alto", "media": "medio", "bassa": "dati insufficienti"}[livello(punti)]


def _migliaia(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _parte(valore: float, pieno: float, punti: float) -> float:
    return min(max(valore, 0), pieno) / pieno * punti


def _giocata(r: RigaPresenza) -> bool:
    return r.minuti > 0 or r.gialli > 0  # ogni cartellino conta, anche dalla panchina


def calcola(
    *,
    storico: list[RigaPresenza],
    data: datetime,
    arbitro: StatArbitro | None,
    formazione_ufficiale: bool,
    avversario_squadra_id: int,
    nome_avversario: str,
    derby: bool,
    avversario_diretto: str = INCERTO,
    subentro: InfoSubentro | None = None,
    tendenza_nota: bool = False,
) -> Affidabilita:
    """Punteggio e motivi in chiaro (ogni voce descrive quello che c'è o che manca)."""
    motivi: list[str] = []
    totale = 0.0

    # minuti nelle tre stagioni (per i subentranti anche le panchine recenti)
    minuti = sum(int(r.minuti) for r in storico)
    stagioni = len({r.stagione for r in storico if r.minuti > 0})
    if subentro is None:
        totale += _parte(minuti, MINUTI_PIENI, 30)
        if minuti > 0:
            motivi.append(
                f"{_migliaia(minuti)} minuti in {stagioni} "
                f"{'stagione' if stagioni == 1 else 'stagioni'}"
            )
        else:
            motivi.append("nessun minuto nei dati")
    else:
        totale += _parte(minuti, MINUTI_PIENI_SUBENTRANTE, 10)
        totale += _parte(subentro.panchine, PANCHINE_PIENE, 20)
        motivi.append(
            f"{subentro.panchine} {'panchina' if subentro.panchine == 1 else 'panchine'} "
            f"recenti, {subentro.ingressi} {'ingresso' if subentro.ingressi == 1 else 'ingressi'}"
            f" ({_migliaia(minuti)} minuti nei dati)"
        )

    # costanza dei gialli: quante partite diverse (non un solo exploit)
    con_giallo = len({r.partita_id for r in storico if r.gialli > 0})
    totale += _parte(con_giallo, PARTITE_CON_GIALLO_PIENE, 15)
    if con_giallo:
        motivi.append(
            f"gialli in {con_giallo} {'partita' if con_giallo == 1 else 'partite diverse'}"
        )
    else:
        motivi.append("nessun giallo nei dati")

    # formazione
    if formazione_ufficiale:
        totale += 15
        motivi.append("panchina ufficiale" if subentro else "formazione ufficiale")
    else:
        totale += 5
        motivi.append("panchina stimata" if subentro else "formazione solo probabile")

    # arbitro
    if arbitro is None:
        motivi.append("arbitro non ancora designato")
    else:
        totale += 4 + _parte(arbitro.partite, PARTITE_ARBITRO_PIENE, 8)
        motivi.append(
            f"arbitro designato ({arbitro.partite} {'partita' if arbitro.partite == 1 else 'partite'})"
            if arbitro.partite else "arbitro designato (nessuna partita nei dati)"
        )

    # avversario diretto (titolari) o tendenza dei cambi (subentranti)
    if subentro is not None:
        if tendenza_nota:
            totale += 10
            motivi.append("tendenza dei cambi della squadra nota")
        else:
            motivi.append("tendenza dei cambi della squadra sconosciuta")
    elif avversario_diretto == CERTO:
        totale += 10
        motivi.append("avversario diretto certo")
    elif avversario_diretto == PROBABILE:
        totale += 5
        motivi.append("avversario diretto probabile")
    else:
        motivi.append("avversario diretto incerto")

    # precedenti con l'avversaria (derby compresi)
    precedenti = len({r.partita_id for r in storico if r.avversario_id == avversario_squadra_id and _giocata(r)})
    totale += _parte(precedenti, PRECEDENTI_PIENI, 8)
    nome = nome_avversario or "l'avversaria"
    if precedenti:
        motivi.append(
            f"{precedenti} {'precedente' if precedenti == 1 else 'precedenti'} contro {nome}"
            + (" (derby)" if derby else "")
        )
    else:
        motivi.append(f"nessun precedente contro {nome}")

    # attività recente
    limite = data - timedelta(days=GIORNI_RECENTI)
    recenti = len({r.partita_id for r in storico if _giocata(r) and limite <= r.data < data})
    totale += _parte(recenti, PARTITE_RECENTI_PIENE, 10)
    if recenti:
        motivi.append(
            f"{recenti} {'partita' if recenti == 1 else 'partite'} negli ultimi {GIORNI_RECENTI} giorni"
        )
    else:
        motivi.append(f"nessuna presenza negli ultimi {GIORNI_RECENTI} giorni")

    return Affidabilita(punti=min(100, int(totale + 0.5)), motivi=tuple(motivi))
