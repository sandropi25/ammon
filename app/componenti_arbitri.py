"""Logica delle pagine Arbitri e scheda arbitro (senza Streamlit): medie di gialli, rossi e
falli degli arbitri dei campionati, dalle partite con i cartellini totali nel database.

"Carriera" qui vuol dire "dal 2023-24": le stagioni coperte dai dati sono quelle da
`PRIMA_STAGIONE` in poi (la 2023 ha solo i totali di partita, le altre anche i giocatori).
Ogni cartellino conta: i totali di partita comprendono quelli presi dalla panchina e un
secondo giallo e' un giallo e un rosso come lo riporta ESPN.

Query raggruppate (una per l'elenco, poche per la scheda, qualunque sia il numero di arbitri
o di partite). Su Postgres SUM e COUNT restituiscono Decimal: ogni aggregato e' convertito
in int. Tutto cio' che esce da qui e' fatto di dataclass e tuple semplici (picklabili, per
`st.cache_data`)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI, STATI_FINITI
from ammonizioni.db.modelli import Arbitro, Partita, Squadra

PRIMA_STAGIONE = 2023
ULTIME_PARTITE = 10
NOTA_CARRIERA = (
    "In carriera = dal 2023-24: i dati coprono le stagioni dal 2023-24 in poi "
    "(prima non sono disponibili)."
)
NOTA_TOTALI = (
    "Cartellini di tutta la partita, entrambe le squadre, anche quelli dalla panchina. "
    "Un secondo giallo conta come un giallo e un rosso, come lo riporta ESPN."
)
CRITERI = {
    "Media gialli": lambda r: (-(r.totale.gialli_media or 0), -r.totale.partite, r.nome.casefold()),
    "Media rossi": lambda r: (-(r.totale.rossi_media or 0), -r.totale.partite, r.nome.casefold()),
    "Media falli": lambda r: (-(r.totale.falli_media or 0), -r.totale.partite, r.nome.casefold()),
    "Partite arbitrate": lambda r: (-r.totale.partite, -(r.totale.gialli_media or 0), r.nome.casefold()),
    "Nome": lambda r: (r.nome.casefold(),),
}


@dataclass(frozen=True)
class Statistiche:
    """Somme di un gruppo di partite arbitrate (solo quelle con i cartellini totali noti)."""

    partite: int = 0
    gialli: int = 0
    rossi: int = 0
    falli: int = 0
    partite_falli: int = 0  # partite con i falli noti (possono mancare)
    con_rosso: int = 0  # partite con almeno un rosso

    def __add__(self, altro: "Statistiche") -> "Statistiche":
        return Statistiche(
            self.partite + altro.partite, self.gialli + altro.gialli, self.rossi + altro.rossi,
            self.falli + altro.falli, self.partite_falli + altro.partite_falli,
            self.con_rosso + altro.con_rosso,
        )

    @property
    def gialli_media(self) -> float | None:
        return self.gialli / self.partite if self.partite else None

    @property
    def rossi_media(self) -> float | None:
        return self.rossi / self.partite if self.partite else None

    @property
    def falli_media(self) -> float | None:
        return self.falli / self.partite_falli if self.partite_falli else None

    @property
    def percentuale_rosso(self) -> float | None:
        return 100 * self.con_rosso / self.partite if self.partite else None


@dataclass(frozen=True)
class RigaArbitro:
    id: int
    nome: str
    campionati: tuple[int, ...]  # in cui ha arbitrato, nell'ordine di CAMPIONATI
    totale: Statistiche


@dataclass(frozen=True)
class ElencoArbitri:
    righe: tuple[RigaArbitro, ...]  # ordinate per media di gialli
    media_gialli_lega: float | None  # media di tutte le partite considerate


@dataclass(frozen=True)
class PartitaArbitrata:
    id: int
    quando: str
    campionato: str
    stagione: str
    casa: str
    trasferta: str
    logo_casa: str | None
    logo_trasferta: str | None
    gol_casa: int | None
    gol_trasferta: int | None
    gialli: int | None  # None: cartellini non noti
    rossi: int | None


@dataclass(frozen=True)
class ConSquadra:
    squadra_id: int
    nome: str
    logo: str | None
    statistiche: Statistiche  # partite arbitrate da lui con questa squadra


@dataclass(frozen=True)
class ProssimaPartita:
    id: int
    quando: str
    campionato: str
    casa: str
    trasferta: str
    logo_casa: str | None
    logo_trasferta: str | None
    con_squadre: tuple[ConSquadra, ...]  # casa e trasferta


@dataclass(frozen=True)
class SchedaArbitro:
    id: int
    nome: str
    totale: Statistiche
    per_campionato: tuple[tuple[str, Statistiche], ...]  # (nome campionato, statistiche)
    per_stagione: tuple[tuple[str, str, Statistiche], ...]  # (campionato, "2025-26", stat.)
    ultime: tuple[PartitaArbitrata, ...]
    prossima: ProssimaPartita | None
    senza_cartellini: int  # partite arbitrate di cui non si conoscono i cartellini


def etichetta_stagione(stagione: int) -> str:
    """2023 -> "2023-24"."""
    return f"{stagione}-{(stagione + 1) % 100:02d}"


def _stat(riga) -> Statistiche:
    """Statistiche da una riga raggruppata (partite, gialli, rossi, con rosso, falli, partite
    con falli): int() su tutto, perche' Postgres restituisce Decimal."""
    partite, gialli, rossi, con_rosso, falli, partite_falli = riga
    return Statistiche(
        int(partite or 0), int(gialli or 0), int(rossi or 0), int(falli or 0),
        int(partite_falli or 0), int(con_rosso or 0),
    )


def _gruppi(s: Session, *filtri) -> dict[tuple[int, int, int], Statistiche]:
    """(arbitro, campionato, stagione) -> statistiche delle partite di campionato finite con
    i cartellini noti. Una sola query raggruppata."""
    righe = s.execute(
        select(
            Partita.arbitro_id, Partita.competizione_id, Partita.stagione,
            func.count(Partita.id), func.sum(Partita.gialli_totali), func.sum(Partita.rossi_totali),
            func.sum(case((Partita.rossi_totali > 0, 1), else_=0)),
            func.sum(Partita.falli_totali), func.count(Partita.falli_totali),
        )
        .where(
            Partita.arbitro_id.is_not(None),
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.stato.in_(STATI_FINITI),
            Partita.gialli_totali.is_not(None),
            Partita.rossi_totali.is_not(None),
            *filtri,
        )
        .group_by(Partita.arbitro_id, Partita.competizione_id, Partita.stagione)
    ).all()
    return {(int(a), int(c), int(st)): _stat(r) for a, c, st, *r in righe}


def _somma(statistiche) -> Statistiche:
    totale = Statistiche()
    for st in statistiche:
        totale = totale + st
    return totale


def carica_elenco(s: Session, campionati: tuple[int, ...]) -> ElencoArbitri:
    """Arbitri che hanno diretto partite dei campionati dati (con i cartellini noti), dal piu'
    severo: media di gialli decrescente. Due query in tutto (statistiche e nomi)."""
    campionati = tuple(c for c in campionati if c in CAMPIONATI)
    if not campionati:
        return ElencoArbitri((), None)
    gruppi = _gruppi(s, Partita.competizione_id.in_(campionati))
    ids = {a for a, _, _ in gruppi}
    nomi = {
        int(i): n for i, n in s.execute(
            select(Arbitro.id, Arbitro.nome_visualizzato).where(Arbitro.id.in_(ids))
        ).all()
    } if ids else {}
    righe = []
    for arbitro in ids:
        suoi = {(c, st): v for (a, c, st), v in gruppi.items() if a == arbitro}
        righe.append(RigaArbitro(
            id=arbitro, nome=nomi.get(arbitro, "?"),
            campionati=tuple(c for c in CAMPIONATI if any(k[0] == c for k in suoi)),
            totale=_somma(suoi.values()),
        ))
    righe.sort(key=CRITERI["Media gialli"])
    lega = _somma(gruppi.values())
    return ElencoArbitri(tuple(righe), lega.gialli_media)


def ordina(righe, criterio: str) -> tuple[RigaArbitro, ...]:
    """Le righe dell'elenco nell'ordine del criterio (uno di `CRITERI`)."""
    return tuple(sorted(righe, key=CRITERI.get(criterio, CRITERI["Media gialli"])))


def _squadre(s: Session, ids: set[int]) -> dict[int, tuple[str, str | None]]:
    if not ids:
        return {}
    logo_attivo = componenti.immagini_attive(s)
    return {
        int(i): (nome, componenti.url_https(logo) if logo_attivo else None)
        for i, nome, logo in s.execute(
            select(Squadra.id, Squadra.nome, Squadra.logo_url).where(Squadra.id.in_(ids))
        ).all()
    }


def _con_squadre(s: Session, arbitro_id: int, squadre: list[int]) -> dict[int, Statistiche]:
    """Statistiche delle partite finite dell'arbitro con ciascuna squadra data (una query)."""
    righe = s.execute(
        select(
            Partita.casa_id, Partita.trasferta_id, Partita.gialli_totali, Partita.rossi_totali,
            Partita.falli_totali,
        ).where(
            Partita.arbitro_id == arbitro_id,
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.stato.in_(STATI_FINITI),
            Partita.gialli_totali.is_not(None),
            Partita.rossi_totali.is_not(None),
            or_(Partita.casa_id.in_(squadre), Partita.trasferta_id.in_(squadre)),
        )
    ).all()
    risultato = {sq: Statistiche() for sq in squadre}
    for casa, trasferta, gialli, rossi, falli in righe:
        parziale = Statistiche(
            1, int(gialli), int(rossi), int(falli or 0), 1 if falli is not None else 0,
            1 if int(rossi) > 0 else 0,
        )
        for sq in (casa, trasferta):
            if sq in risultato:
                risultato[sq] = risultato[sq] + parziale
    return risultato


def scheda_arbitro(s: Session, arbitro_id: int, adesso: datetime) -> SchedaArbitro | None:
    """Scheda di un arbitro: totale dal 2023-24, per campionato e per stagione, ultime 10
    partite, prossima partita designata con le sue medie per ciascuna squadra. None se
    l'arbitro non esiste. Poche query, nessuna per partita."""
    arbitro = s.get(Arbitro, arbitro_id)
    if arbitro is None:
        return None
    gruppi = {k[1:]: v for k, v in _gruppi(s, Partita.arbitro_id == arbitro_id).items()}
    per_campionato = tuple(
        (NOMI_CAMPIONATI[c], _somma(v for (cc, _), v in gruppi.items() if cc == c))
        for c in CAMPIONATI if any(cc == c for cc, _ in gruppi)
    )
    per_stagione = tuple(
        (NOMI_CAMPIONATI[c], etichetta_stagione(st), gruppi[(c, st)])
        for c in CAMPIONATI
        for st in sorted((st for cc, st in gruppi if cc == c), reverse=True)
    )
    ultime_p = s.execute(
        select(Partita).where(
            Partita.arbitro_id == arbitro_id,
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.stato.in_(STATI_FINITI),
        ).order_by(Partita.data_utc.desc(), Partita.id.desc()).limit(ULTIME_PARTITE)
    ).scalars().all()
    prossima_p = s.execute(
        select(Partita).where(
            Partita.arbitro_id == arbitro_id,
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.stato.not_in(STATI_FINITI),
            Partita.stato.not_in(("PST", "CANC")),
            Partita.data_utc >= adesso,
        ).order_by(Partita.data_utc, Partita.id).limit(1)
    ).scalars().first()
    ids_squadre = {p.casa_id for p in ultime_p} | {p.trasferta_id for p in ultime_p}
    if prossima_p is not None:
        ids_squadre |= {prossima_p.casa_id, prossima_p.trasferta_id}
    squadre = _squadre(s, ids_squadre)

    def nome(sq: int) -> str:
        return squadre.get(sq, (str(sq), None))[0]

    def logo(sq: int) -> str | None:
        return squadre.get(sq, (str(sq), None))[1]

    ultime = tuple(
        PartitaArbitrata(
            id=p.id, quando=componenti.data_italiana(p.data_utc),
            campionato=NOMI_CAMPIONATI.get(p.competizione_id, ""),
            stagione=etichetta_stagione(p.stagione), casa=nome(p.casa_id),
            trasferta=nome(p.trasferta_id), logo_casa=logo(p.casa_id),
            logo_trasferta=logo(p.trasferta_id), gol_casa=p.gol_casa, gol_trasferta=p.gol_trasferta,
            gialli=p.gialli_totali, rossi=p.rossi_totali,
        )
        for p in ultime_p
    )
    prossima = None
    if prossima_p is not None:
        con = _con_squadre(s, arbitro_id, [prossima_p.casa_id, prossima_p.trasferta_id])
        prossima = ProssimaPartita(
            id=prossima_p.id, quando=componenti.data_italiana(prossima_p.data_utc),
            campionato=NOMI_CAMPIONATI.get(prossima_p.competizione_id, ""),
            casa=nome(prossima_p.casa_id), trasferta=nome(prossima_p.trasferta_id),
            logo_casa=logo(prossima_p.casa_id), logo_trasferta=logo(prossima_p.trasferta_id),
            con_squadre=tuple(
                ConSquadra(sq, nome(sq), logo(sq), con[sq])
                for sq in (prossima_p.casa_id, prossima_p.trasferta_id)
            ),
        )
    arbitrate = s.execute(
        select(func.count(Partita.id)).where(
            Partita.arbitro_id == arbitro_id,
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.stato.in_(STATI_FINITI),
        )
    ).scalar()
    totale = _somma(gruppi.values())
    return SchedaArbitro(
        id=arbitro.id, nome=arbitro.nome_visualizzato, totale=totale,
        per_campionato=per_campionato, per_stagione=per_stagione, ultime=ultime,
        prossima=prossima, senza_cartellini=max(int(arbitrate or 0) - totale.partite, 0),
    )


def numero(valore: float | None, cifre: int = 2) -> str:
    """Numero con la virgola ("4,25"); "–" se non c'e' (nessuna partita)."""
    return "–" if valore is None else f"{valore:.{cifre}f}".replace(".", ",")


def percentuale(valore: float | None) -> str:
    return "–" if valore is None else f"{valore:.0f}%"


def id_arbitro(valore) -> int | None:
    """Id dal parametro ?arbitro= dell'indirizzo; None se manca o non e' un numero."""
    try:
        numero_ = int(valore)
    except (TypeError, ValueError):
        return None
    return numero_ if numero_ > 0 else None
