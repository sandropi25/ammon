"""Pronostici marcatori delle prossime partite (app beta e cernita automatica)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ammonizioni.db.modelli import Partita
from ammonizioni.marcatori.dati import carica, costruisci_storico, partita_m, rosa_partita
from ammonizioni.marcatori.modello import Previsione, Storico, carica_parametri
from ammonizioni.motore.rivalita import derby_noti


@dataclass(frozen=True)
class Pronostico:
    partita_id: int
    formazioni: str  # "ufficiali" | "probabili" | "" (nessuna formazione: niente pronostico)
    previsioni: list[Previsione]


def storico_fino_a(s: Session, prima_di: datetime) -> Storico:
    partite, presenze = carica(s, prima_di=prima_di)
    storico = costruisci_storico(partite, presenze, carica_parametri(s))
    storico.derby = derby_noti(s)
    return storico


def pronostica(s: Session, partite: list[Partita], storico: Storico | None = None) -> list[Pronostico]:
    """Un pronostico per partita, con lo storico delle partite finite prima della piu' vicina.
    Lo storico si puo' passare gia' pronto (l'app lo tiene in cache)."""
    if not partite:
        return []
    if storico is None:
        storico = storico_fino_a(s, min(partita_m(p).data for p in partite))
    risultato = []
    for p in partite:
        rosa, tipo = rosa_partita(s, p)
        previsioni = storico.prevedi(partita_m(p), rosa) if rosa else []
        risultato.append(Pronostico(p.id, tipo, previsioni))
    return risultato
