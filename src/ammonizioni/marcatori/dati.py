"""Caricamento in blocco per il modello marcatori: due query, niente query per partita."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.config import CAMPIONATI, STATI_FINITI
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza
from ammonizioni.marcatori.modello import Giocante, PartitaM, PresenzaM, Storico

STAGIONE_INIZIO = 2024


def _utc(quando: datetime) -> datetime:
    return quando.replace(tzinfo=timezone.utc) if quando.tzinfo is None else quando


def partita_m(p: Partita) -> PartitaM:
    return PartitaM(
        p.id, _utc(p.data_utc), p.competizione_id, p.stagione, p.casa_id, p.trasferta_id,
        p.gol_casa, p.gol_trasferta,
    )


def carica(
    s: Session, campionati=CAMPIONATI, prima_di: datetime | None = None
) -> tuple[list[PartitaM], dict[int, list[PresenzaM]]]:
    """Partite finite con statistiche dei campionati (dal 2024), in ordine di data, e le loro
    presenze. Il ruolo mancante della presenza si prende dall'anagrafica del giocatore."""
    filtro = [
        Partita.competizione_id.in_(tuple(campionati)),
        Partita.stagione >= STAGIONE_INIZIO,
        Partita.stato.in_(STATI_FINITI),
        Partita.statistiche_scaricate.is_(True),
    ]
    if prima_di is not None:
        filtro.append(Partita.data_utc < prima_di)
    partite = [
        partita_m(p)
        for p in s.scalars(select(Partita).where(*filtro).order_by(Partita.data_utc, Partita.id))
    ]
    presenze: dict[int, list[PresenzaM]] = defaultdict(list)
    righe = s.execute(
        select(
            Presenza.partita_id, Presenza.giocatore_id, Presenza.squadra_id, Presenza.titolare,
            Presenza.ruolo, Giocatore.ruolo, Presenza.minuti, Presenza.gol, Presenza.tiri,
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(*filtro)
    )
    for pid, gid, sid, tit, ruolo, ruolo_anag, minuti, gol, tiri in righe:
        presenze[pid].append(
            PresenzaM(gid, sid, bool(tit), ruolo or ruolo_anag, minuti or 0, gol or 0, tiri or 0)
        )
    return partite, presenze


def costruisci_storico(partite, presenze, parametri) -> Storico:
    storico = Storico(parametri)
    for p in partite:
        storico.aggiorna(p, presenze.get(p.id, []))
    return storico


def rosa_partita(s: Session, partita: Partita) -> tuple[list[Giocante], str]:
    """Giocatori della partita: ufficiali + panchina se ci sono, altrimenti le probabili
    salvate, altrimenti quelle calcolate dalle ultime partite (solo titolari). Restituisce
    anche il tipo ("ufficiali", "probabili", "stimate" o "")."""
    righe = s.execute(
        select(Formazione.giocatore_id, Formazione.squadra_id, Formazione.tipo, Giocatore.ruolo)
        .join(Giocatore, Giocatore.id == Formazione.giocatore_id)
        .where(Formazione.partita_id == partita.id)
    ).all()
    ufficiali = [r for r in righe if r.tipo in ("ufficiale", "panchina")]
    if any(r.tipo == "ufficiale" for r in ufficiali):
        return [Giocante(r.giocatore_id, r.squadra_id, r.tipo == "ufficiale", r.ruolo)
                for r in ufficiali], "ufficiali"
    probabili = [r for r in righe if r.tipo == "probabile"]
    if probabili:
        return [Giocante(r.giocatore_id, r.squadra_id, True, r.ruolo) for r in probabili], "probabili"
    # partita ancora lontana: probabili calcolate dalle ultime partite (come l'app dei cartellini)
    from ammonizioni.caricamento.formazioni import probabili_automatiche, ultimo_xi

    rosa = []
    for squadra_id in (partita.casa_id, partita.trasferta_id):
        xi = probabili_automatiche(s, squadra_id, partita.data_utc) or ultimo_xi(
            s, squadra_id, partita.data_utc
        )
        rosa += [Giocante(t.giocatore_id, squadra_id, True, t.ruolo) for t in xi]
    return rosa, "stimate" if rosa else ""
