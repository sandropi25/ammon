"""Pronostici marcatori delle prossime partite (app beta e cernita automatica)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ammonizioni.db.modelli import Partita
from ammonizioni.marcatori.dati import (
    carica, costruisci_storico, partita_m, rosa_partita, rosa_partita_per_squadra, stimate_squadra,
)
from ammonizioni.marcatori.modello import Previsione, Storico, carica_parametri
from ammonizioni.motore.rivalita import derby_noti


SOGLIA_ESCLUSI = 0.15  # sotto questa probabilita' l'assenza non fa notizia


@dataclass(frozen=True)
class Pronostico:
    partita_id: int
    formazioni: str  # "ufficiali" | "miste" | "probabili" | "stimate" | "" (niente pronostico)
    previsioni: list[Previsione]
    gol_attesi: tuple[float, float] = (0.0, 0.0)  # (casa, trasferta) per la partita
    # con l'ufficiale: chi sarebbe stato tra i favoriti ma non parte titolare
    # (giocatore, probabilita' da titolare stimata, in panchina?)
    esclusi: tuple[tuple[int, float, bool], ...] = ()
    tipi_squadra: tuple[str, str] = ("", "")  # (casa, trasferta): ufficiale/probabile/stimata


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
        pm = partita_m(p)
        per_squadra = rosa_partita_per_squadra(s, p)
        rosa, tipo = rosa_partita(s, p, per_squadra)
        previsioni = storico.prevedi(pm, rosa) if rosa else []
        casa, trasferta, _ = storico.gol_attesi(pm)
        esclusi = []
        for squadra_id, (giocanti, tipo_squadra) in per_squadra.items():
            if tipo_squadra != "ufficiale":
                continue
            titolari = {g.giocatore_id for g in giocanti if g.titolare}
            panchina = {g.giocatore_id for g in giocanti if not g.titolare}
            attesi = [g for g in stimate_squadra(s, squadra_id, p.data_utc) if g.giocatore_id not in titolari]
            esclusi += [
                (x.giocatore_id, x.probabilita, x.giocatore_id in panchina)
                for x in storico.prevedi(pm, attesi) if x.probabilita >= SOGLIA_ESCLUSI
            ]
        risultato.append(Pronostico(
            p.id, tipo, previsioni, (casa, trasferta), tuple(sorted(esclusi, key=lambda e: -e[1])),
            (per_squadra[p.casa_id][1], per_squadra[p.trasferta_id][1]),
        ))
    return risultato
