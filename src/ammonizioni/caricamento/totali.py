"""Cartellini totali di partita e stagione 2023.

I totali (`gialli_totali`, `rossi_totali`, `falli_totali`) delle partite con le statistiche dei
giocatori si ricavano dalle presenze (gialli e rossi dalla panchina compresi); per le altre
arrivano dal tabellone ESPN (eventi `details`). La stagione 2023 si carica una volta sola,
senza le statistiche dei giocatori: calendario con i totali dal tabellone (una richiesta per
campionato e anno solare) e arbitri da football-data.org (una richiesta per campionato). Il
modello resta sulle stagioni di `STAGIONI`: la 2023 non ha presenze, quindi non entra nelle
sue medie."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ammonizioni.caricamento import arbitri_fd
from ammonizioni.caricamento.notturno import salva_partita
from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Partita, Presenza
from ammonizioni.fonti.base import ErroreFonte, Fonte
from ammonizioni.fonti.limite import LimiteSuperato

log = logging.getLogger(__name__)

STAGIONE_SOLO_TOTALI = 2023
CALENDARI_2023 = "stagione_2023_calendari"  # campionati con calendario e totali gia' caricati
ARBITRI_2023 = "stagione_2023_arbitri"  # campionati con gli arbitri gia' collegati


def riempi_da_presenze(s: Session) -> int:
    """Totali delle partite con le statistiche scaricate e ancora senza totali, dalle
    presenze: una query raggruppata e un aggiornamento in blocco. Restituisce quante partite
    ha aggiornato. Su Postgres SUM restituisce Decimal: convertito in int."""
    righe = s.execute(
        select(
            Partita.id,
            func.sum(Presenza.gialli),
            func.sum(Presenza.rossi),
            func.sum(Presenza.falli_commessi),
        )
        .join(Presenza, Presenza.partita_id == Partita.id)
        .where(
            Partita.statistiche_scaricate.is_(True),
            Partita.gialli_totali.is_(None),
        )
        .group_by(Partita.id)
    ).all()
    if not righe:
        return 0
    s.execute(
        update(Partita),
        [
            {
                "id": int(pid),
                "gialli_totali": int(g or 0),
                "rossi_totali": int(r or 0),
                "falli_totali": int(f or 0),
            }
            for pid, g, r, f in righe
        ],
    )
    s.commit()
    return len(righe)


def carica_stagione_2023(s: Session, fonte: Fonte, fonte_fd) -> bool:
    """Passo una tantum per campionato (flag in Impostazione): calendario 2023-24 con i
    totali dal tabellone ESPN e arbitri da football-data.org. Nessuna statistica di
    giocatore. Un campionato gia' fatto non fa nessuna richiesta. True se non ci sono stati
    errori; `LimiteSuperato` della fonte ESPN risale (come negli altri passi dello storico).
    Senza chiave football-data i calendari si caricano e gli arbitri restano per un'altra
    volta."""
    completo = True
    for campionato in CAMPIONATI:
        nome = NOMI_CAMPIONATI[campionato]
        calendari = set(repo.leggi_impostazione(s, CALENDARI_2023, []) or [])
        if campionato not in calendari:
            try:
                partite = fonte.partite(campionato, STAGIONE_SOLO_TOTALI)
            except ErroreFonte as errore:
                log.warning("Calendario %s %s non caricato: %s", nome, STAGIONE_SOLO_TOTALI, errore)
                completo = False
                continue
            for dati in partite:
                salva_partita(s, dati)
            calendari.add(campionato)
            repo.scrivi_impostazione(s, CALENDARI_2023, sorted(calendari))
            s.commit()
        arbitri = set(repo.leggi_impostazione(s, ARBITRI_2023, []) or [])
        if campionato in arbitri or fonte_fd is None:
            continue
        if not getattr(fonte_fd, "chiave", None):
            log.warning("Arbitri %s %s non collegati: manca la chiave football-data.org",
                        nome, STAGIONE_SOLO_TOTALI)
            continue
        try:
            arbitri_fd.collega(
                s, fonte_fd, campionato,
                date(STAGIONE_SOLO_TOTALI, 7, 1), date(STAGIONE_SOLO_TOTALI + 1, 6, 30),
            )
        except (ErroreFonte, LimiteSuperato) as errore:
            s.rollback()
            log.warning("Arbitri %s %s non collegati: %s", nome, STAGIONE_SOLO_TOTALI, errore)
            completo = False
            continue
        arbitri.add(campionato)
        repo.scrivi_impostazione(s, ARBITRI_2023, sorted(arbitri))
        s.commit()
    return completo
