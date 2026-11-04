"""Formazioni: ultimo XI di una squadra, formazioni probabili e riepilogo dei cambi."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza
from ammonizioni.motore.tipi import Titolare

RUOLI = ("G", "D", "M", "F")


def titolare_da(g: Giocatore, squadra_id: int, griglia: str | None, ruolo: str | None) -> Titolare:
    """Titolare del motore; ruolo mancante o sconosciuto -> "M"."""
    ruolo = ruolo or g.ruolo
    return Titolare(
        giocatore_id=g.id,
        nome=g.nome,
        squadra_id=squadra_id,
        ruolo=ruolo if ruolo in RUOLI else "M",
        griglia=griglia,
        sofascore_url=g.sofascore_url,
    )


def ultimo_xi(s: Session, squadra_id: int, prima_di: datetime) -> list[Titolare]:
    """Titolari dell'ultima partita (qualsiasi competizione) della squadra prima di `prima_di`."""
    ultima = s.execute(
        select(Partita.id)
        .join(Presenza, Presenza.partita_id == Partita.id)
        .where(
            Presenza.squadra_id == squadra_id,
            Presenza.titolare.is_(True),
            Partita.data_utc < prima_di,
        )
        .order_by(Partita.data_utc.desc())
        .limit(1)
    ).scalar()
    if ultima is None:
        return []
    righe = s.execute(
        select(Presenza, Giocatore)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(
            Presenza.partita_id == ultima,
            Presenza.squadra_id == squadra_id,
            Presenza.titolare.is_(True),
        )
        .order_by(Giocatore.id)
    ).all()
    return [titolare_da(g, squadra_id, p.griglia, p.ruolo) for p, g in righe]


def salva_probabili(s: Session, partita_id: int, titolari_per_squadra: dict[int, list[int]]) -> None:
    """Sostituisce le formazioni probabili della partita (le ufficiali restano)."""
    s.execute(
        delete(Formazione).where(
            Formazione.partita_id == partita_id, Formazione.tipo == "probabile"
        )
    )
    for squadra_id, giocatori in titolari_per_squadra.items():
        for giocatore_id in dict.fromkeys(giocatori):
            s.add(
                Formazione(
                    partita_id=partita_id,
                    squadra_id=squadra_id,
                    giocatore_id=giocatore_id,
                    tipo="probabile",
                )
            )
    s.flush()


def _per_squadra(s: Session, partita_id: int, tipo: str) -> dict[int, set[int]]:
    risultato: dict[int, set[int]] = {}
    righe = s.execute(
        select(Formazione.squadra_id, Formazione.giocatore_id).where(
            Formazione.partita_id == partita_id, Formazione.tipo == tipo
        )
    ).all()
    for squadra_id, giocatore_id in righe:
        risultato.setdefault(squadra_id, set()).add(giocatore_id)
    return risultato


def riepilogo_cambi(
    s: Session, partita_id: int
) -> dict[int, tuple[list[int], list[int]]]:
    """Per squadra (entrati, usciti) della formazione ufficiale rispetto alla probabile.
    Vuoto se manca l'una o l'altra."""
    probabili = _per_squadra(s, partita_id, "probabile")
    ufficiali = _per_squadra(s, partita_id, "ufficiale")
    if not probabili or not ufficiali:
        return {}
    return {
        squadra_id: (
            sorted(xi - probabili.get(squadra_id, set())),
            sorted(probabili.get(squadra_id, set()) - xi),
        )
        for squadra_id, xi in ufficiali.items()
    }
