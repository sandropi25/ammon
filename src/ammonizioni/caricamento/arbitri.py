"""Nomi degli arbitri: la stessa persona arriva scritta in modi diversi
("D. Doveri", "Daniele Doveri, Italy", "DOVERI, Daniele"); si identifica dal cognome."""
from __future__ import annotations

import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.config import SERIE_A
from ammonizioni.db.modelli import Arbitro

# Paesi che l'API aggiunge dopo la virgola ("Daniele Doveri, Italy").
PAESI = frozenset(
    {
        "italy", "england", "spain", "france", "germany", "portugal", "netherlands",
        "belgium", "poland", "romania", "turkey", "slovenia", "croatia", "serbia",
        "scotland", "switzerland", "austria", "sweden", "norway", "denmark",
    }
)


def _senza_accenti(testo: str) -> str:
    scomposto = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in scomposto if not unicodedata.combining(c))


def _senza_paese(nome: str) -> str:
    """Nome com'è, ma senza il suffisso ", <paese>"."""
    parti = [p.strip() for p in nome.split(",")]
    if len(parti) == 2 and _senza_accenti(parti[1]).lower() in PAESI:
        return parti[0]
    return nome.strip()


def normalizza(nome: str) -> str:
    """Cognome in minuscolo e senza accenti: ultima parola più lunga di 2 caratteri
    (le iniziali puntate non contano). Stringa vuota se non c'è nulla."""
    testo = _senza_accenti(nome).lower()
    # Dopo la virgola c'è un paese ("Daniele Doveri, Italy": da scartare) oppure il nome
    # ("DOVERI, Daniele": cognome per primo). In entrambi i casi conta la parte prima.
    testo = testo.split(",")[0]
    parole = testo.replace(".", " ").split()
    lunghe = [p for p in parole if len(p) > 2]
    if lunghe:
        return lunghe[-1]
    return parole[-1] if parole else ""


def chiave_arbitro(nome: str, campionato_id: int | None = None) -> str:
    """Chiave di identità dell'arbitro: il cognome normalizzato. Per i campionati diversi dalla
    Serie A è preceduta dal campionato ("140:martinez"), così due arbitri con lo stesso cognome
    in campionati diversi restano distinti e le statistiche della Serie A non cambiano."""
    chiave = normalizza(nome)
    if chiave and campionato_id is not None and campionato_id != SERIE_A:
        return f"{campionato_id}:{chiave}"
    return chiave


def trova_o_crea(
    s: Session, nome: str | None, campionato_id: int | None = None
) -> Arbitro | None:
    """Restituisce l'arbitro con la stessa chiave (cognome normalizzato; con il campionato
    se non è la Serie A), creandolo se manca."""
    if not nome or not nome.strip():
        return None
    chiave = chiave_arbitro(nome, campionato_id)
    if not chiave:
        return None
    esistente = s.scalars(select(Arbitro).where(Arbitro.nome_normalizzato == chiave)).first()
    if esistente is not None:
        return esistente
    arbitro = Arbitro(nome_normalizzato=chiave, nome_visualizzato=_senza_paese(nome))
    s.add(arbitro)
    s.flush()
    return arbitro
