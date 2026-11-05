"""Logica della pagina Partite calde e dell'elenco di derby e campi caldi (senza Streamlit).

Il calore di ogni partita in programma è calcolato con query raggruppate (nessuna query per
partita): tutti i totali di cartellini delle ultime tre stagioni in una sola lettura, poi i
conti in Python."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.config import (
    CAMPIONATI,
    STAGIONE_CORRENTE,
    STATI_FINITI,
)
from ammonizioni.db.modelli import Arbitro, Partita, Presenza, Squadra
from ammonizioni.motore import rivalita
from ammonizioni.motore.fattori.contesto import posta_in_classifica

PRECEDENTI_MAX = 5
GIORNI_PRIMA_SEZIONE = 7


def _utc(dt: datetime) -> datetime:
    """Datetime aware UTC (le colonne lo sono già; per sicurezza nei confronti)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Giocata:
    """Una partita con statistiche: chi, quando, quanti cartellini (gialli + rossi)."""
    data: datetime
    casa: int
    trasferta: int
    competizione: int
    stagione: int
    arbitro: int | None
    cartellini: int


def _giocate(s: Session, stagione_minima: int, fino_a: datetime) -> list[_Giocata]:
    """Totali di cartellini di tutte le partite con statistiche dalla stagione data, con
    una sola query raggruppata. Su Postgres SUM restituisce Decimal: convertito in int."""
    righe = s.execute(
        select(
            Partita.data_utc, Partita.casa_id, Partita.trasferta_id, Partita.competizione_id,
            Partita.stagione, Partita.arbitro_id,
            func.sum(Presenza.gialli + Presenza.rossi),
        )
        .join(Presenza, Presenza.partita_id == Partita.id)
        .where(
            Partita.statistiche_scaricate.is_(True),
            Partita.stagione >= stagione_minima,
            Partita.data_utc < fino_a,
        )
        .group_by(
            Partita.id, Partita.data_utc, Partita.casa_id, Partita.trasferta_id,
            Partita.competizione_id, Partita.stagione, Partita.arbitro_id,
        )
    ).all()
    giocate = [
        _Giocata(_utc(d), c, t, comp, st, arb, int(tot or 0))
        for d, c, t, comp, st, arb, tot in righe
    ]
    giocate.sort(key=lambda g: g.data)
    return giocate


def _media(valori: list[int]) -> float | None:
    return sum(valori) / len(valori) if valori else None


def calore_partite(s: Session, partite: list[Partita]) -> dict[int, componenti.Calore]:
    """Calore di più partite in programma, con poche query raggruppate."""
    if not partite:
        return {}
    ultima = max(_utc(p.data_utc) for p in partite)
    giocate = _giocate(s, min(p.stagione for p in partite) - 2, ultima)

    per_squadra: dict[int, list[_Giocata]] = {}
    per_coppia: dict[frozenset[int], list[_Giocata]] = {}
    per_arbitro: dict[int, list[_Giocata]] = {}
    per_lega: dict[tuple[int, int], list[_Giocata]] = {}
    for g in giocate:  # già in ordine di data
        for sq in (g.casa, g.trasferta):
            per_squadra.setdefault(sq, []).append(g)
        per_coppia.setdefault(frozenset((g.casa, g.trasferta)), []).append(g)
        if g.arbitro is not None:
            per_arbitro.setdefault(g.arbitro, []).append(g)
        per_lega.setdefault((g.competizione, g.stagione), []).append(g)

    # derby, campi caldi (con il motivo) e nomi
    derby = {d.coppia: d for d in rivalita.elenco_derby(s)}
    primo = min(_utc(p.data_utc) for p in partite)
    campi_caldi: dict[int, dict[int, str]] = {}  # stagione -> squadra -> motivo
    nomi_arbitri: dict[int, str] = {}
    ids_arbitri = {p.arbitro_id for p in partite if p.arbitro_id is not None}
    if ids_arbitri:
        nomi_arbitri = {
            a.id: a.nome_visualizzato
            for a in s.execute(select(Arbitro).where(Arbitro.id.in_(ids_arbitri))).scalars()
        }

    # posta in classifica: risultati dei campionati nella stagione, in ordine di data
    risultati: dict[tuple[int, int], list[tuple[datetime, int, int, int, int]]] = {}
    for competizione, stagione in {(p.competizione_id, p.stagione) for p in partite}:
        if competizione not in CAMPIONATI:
            continue
        risultati[(competizione, stagione)] = sorted(
            (_utc(d), c, t, gc, gt)
            for d, c, t, gc, gt in s.execute(
                select(
                    Partita.data_utc, Partita.casa_id, Partita.trasferta_id,
                    Partita.gol_casa, Partita.gol_trasferta,
                ).where(
                    Partita.competizione_id == competizione,
                    Partita.stagione == stagione,
                    Partita.stato.in_(STATI_FINITI),
                    Partita.gol_casa.is_not(None),
                    Partita.gol_trasferta.is_not(None),
                )
            ).all()
        )
    posta_cache: dict[tuple[int, int, int, int], str | None] = {}

    ids_squadre = {p.casa_id for p in partite} | {p.trasferta_id for p in partite}
    nomi = dict(
        s.execute(select(Squadra.id, Squadra.nome).where(Squadra.id.in_(ids_squadre))).all()
    )

    risultato: dict[int, componenti.Calore] = {}
    for p in partite:
        quando = _utc(p.data_utc)
        if p.stagione not in campi_caldi:
            campi_caldi[p.stagione] = {
                c.squadra_id: c.motivo for c in rivalita.elenco_campi_caldi(s, p.stagione, primo)
            }
        caldi = campi_caldi[p.stagione]

        def prima(lista: list[_Giocata]) -> list[_Giocata]:
            return lista[: bisect_left([g.data for g in lista], quando)]

        # media dei cartellini del campionato: stagione della partita e precedente
        lega = [
            g.cartellini
            for stagione in (p.stagione, p.stagione - 1)
            for g in prima(per_lega.get((p.competizione_id, stagione), []))
        ]
        media_lega = _media(lega) or componenti.MEDIA_LEGA_PREDEFINITA

        precedenti = [
            g.cartellini
            for g in prima(per_coppia.get(frozenset((p.casa_id, p.trasferta_id)), []))[-PRECEDENTI_MAX:]
        ]
        medie_squadre = []
        for sq in (p.casa_id, p.trasferta_id):
            sue = [g.cartellini for g in prima(per_squadra.get(sq, [])) if g.stagione == p.stagione]
            medie_squadre.append(
                _media(sue) if len(sue) >= componenti.PARTITE_SQUADRA_MINIME else None
            )
        arbitro_medi, arbitro_n = None, 0
        if p.arbitro_id is not None:
            sue = [g.cartellini for g in prima(per_arbitro.get(p.arbitro_id, []))]
            arbitro_medi, arbitro_n = _media(sue), len(sue)

        posta = []
        giocati = risultati.get((p.competizione_id, p.stagione), [])
        n_prima = bisect_left([r[0] for r in giocati], quando)
        for sq in (p.casa_id, p.trasferta_id):
            chiave = (p.competizione_id, p.stagione, n_prima, sq)
            if chiave not in posta_cache:
                posta_cache[chiave] = posta_in_classifica(
                    [(c, t, gc, gt) for _, c, t, gc, gt in giocati[:n_prima]], sq
                ) if giocati else None
            if posta_cache[chiave]:
                posta.append((nomi[sq], posta_cache[chiave]))

        d = derby.get(frozenset((p.casa_id, p.trasferta_id)))
        campo = caldi.get(p.casa_id)
        risultato[p.id] = componenti.calore_partita(
            derby=d.motivo if d else None,
            campo_caldo=campo,
            precedenti=precedenti,
            arbitro=nomi_arbitri.get(p.arbitro_id),
            arbitro_medi=arbitro_medi,
            arbitro_partite=arbitro_n,
            medie_squadre=(medie_squadre[0], medie_squadre[1]),
            media_lega=media_lega,
            posta=tuple(posta),
        )
    return risultato


def partite_calde(
    s: Session, ora: datetime, campionati: tuple[int, ...] = CAMPIONATI
) -> list[componenti.RigaPartita]:
    """Tutte le partite in programma dei campionati dati, da `ora` in poi, che risultano
    calde (derby, campo caldo o cartellini attesi alti), in ordine di data, con i
    cartellini attesi e i motivi."""
    partite = list(
        s.execute(
            select(Partita)
            .where(
                Partita.competizione_id.in_(campionati),
                Partita.data_utc >= ora,
                Partita.stato.notin_((*STATI_FINITI, "PST", "CANC")),
            )
            .order_by(Partita.data_utc, Partita.id)
        ).scalars()
    )
    calore = calore_partite(s, partite)
    calde = [p for p in partite if calore[p.id].calda]
    righe = componenti.righe_partite(s, calde)
    return [
        replace(r, calda=True, attesi=calore[r.id].attesi, motivi=calore[r.id].motivi)
        for r in righe
    ]


def separa_prossimi_giorni(
    righe: list[componenti.RigaPartita], adesso: datetime
) -> tuple[list[componenti.RigaPartita], list[componenti.RigaPartita]]:
    """(partite dei prossimi 7 giorni, il resto della stagione) dalle righe da `adesso` in poi."""
    fine = adesso + timedelta(days=GIORNI_PRIMA_SEZIONE)
    future = [r for r in righe if r.data_utc >= adesso]
    return (
        [r for r in future if r.data_utc <= fine],
        [r for r in future if r.data_utc > fine],
    )


# ---------------------------------------------------------------- elenco per le Impostazioni

@dataclass(frozen=True)
class ElencoRivalita:
    """Derby riconosciuti e campi caldi calcolati, con il motivo, solo da leggere."""
    derby: tuple[tuple[str, str], ...]  # (campionato, testo)
    campi_caldi: tuple[str, ...]


def elenco_rivalita(s: Session, adesso: datetime) -> ElencoRivalita:
    derby = tuple(
        (rivalita.nome_campionato(d.campionato) or "Inserito a mano", f"{d.nome_a} – {d.nome_b}")
        for d in rivalita.elenco_derby(s)
    )
    campi = tuple(c.motivo for c in rivalita.elenco_campi_caldi(s, STAGIONE_CORRENTE, adesso))
    return ElencoRivalita(derby=derby, campi_caldi=campi)

