"""Logica della pagina Cerca (senza Streamlit): indice dei nomi, ricerca senza accenti,
scheda del giocatore e partite in programma della squadra.

Ogni cartellino conta: i gialli presi dalla panchina (0 minuti) entrano nei totali e nei
valori per 90'; le presenze sono solo le partite con minuti > 0. Su Postgres SUM/COUNT
restituiscono Decimal: ogni aggregato passa da `_n` prima di qualsiasi calcolo."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.config import (
    COMPETIZIONI,
    SERIE_A,
    STAGIONE_CORRENTE,
    campionato_di,
)
from ammonizioni.db.modelli import (
    Arbitro,
    Giocatore,
    Partita,
    Presenza,
    Squadra,
)
from ammonizioni.motore import rivalita
from ammonizioni.motore.fattori.situazione import _soglie_diffida
from ammonizioni.motore.mercati import MercatoAmmonizioni
from ammonizioni.motore.pesi import carica_pesi
from ammonizioni.motore.tipi import Candidato

MAX_RISULTATI = 20
MIN_CARATTERI = 2
GIORNI_SQUADRA = 30
ULTIME_PARTITE = 5

NOMI_COMPETIZIONI: dict[int, str] = {
    135: "Serie A", 137: "Coppa Italia", 140: "Liga", 143: "Copa del Rey",
    2: "Champions League", 3: "Europa League", 848: "Conference League",
}
_ORDINE_COMPETIZIONI = {c: i for i, c in enumerate(NOMI_COMPETIZIONI)}
_SPECIALI = str.maketrans({"ø": "o", "ł": "l", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i"})


def _n(valore) -> int:
    """Intero da un aggregato SQL (Decimal su Postgres, None se non ci sono righe)."""
    return int(valore or 0)


# ---------------------------------------------------------------- formattazione

def data_estesa(dt_utc: datetime) -> str:
    """"domenica 8 novembre 2026 · 20:45" in Europe/Rome."""
    locale = dt_utc.astimezone(componenti.ROMA)
    return (
        f"{componenti.GIORNI_ESTESI[locale.weekday()]} {locale.day} "
        f"{componenti.MESI[locale.month - 1]} {locale.year} · {locale:%H:%M}"
    )


def per90(valore: int, minuti: int) -> float | None:
    return valore / minuti * 90 if minuti > 0 else None


def testo_per90(valore: float | None) -> str:
    return "–" if valore is None else f"{valore:.2f}".replace(".", ",")


# ---------------------------------------------------------------- ricerca

def normalizza(testo: str) -> str:
    """Minuscolo senza accenti né segni ("Çalhanoğlu" -> "calhanoglu"), spazi ridotti."""
    s = unicodedata.normalize("NFKD", testo.casefold().translate(_SPECIALI))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


@dataclass(frozen=True)
class GiocatoreTrovato:
    id: int
    nome: str
    squadra: str
    ruolo: str
    norm: str


@dataclass(frozen=True)
class SquadraTrovata:
    id: int
    nome: str
    campionati: frozenset[int]
    norm: str


@dataclass(frozen=True)
class Indice:
    giocatori: tuple[GiocatoreTrovato, ...]
    squadre: tuple[SquadraTrovata, ...]


def carica_indice(s: Session) -> Indice:
    """Tutti i nomi (con la squadra attuale del giocatore e i campionati della squadra),
    in poche query: da mettere in cache e poi cercare in Python."""
    ultima = (
        select(
            Presenza.giocatore_id.label("g"),
            Presenza.squadra_id.label("sq"),
            Presenza.ruolo.label("ruolo"),
            func.row_number().over(
                partition_by=Presenza.giocatore_id, order_by=Partita.data_utc.desc()
            ).label("n"),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .subquery()
    )
    nomi_squadre = {q.id: q.nome for q in s.execute(select(Squadra)).scalars()}
    attuali = {g: (sq, ruolo) for g, sq, ruolo in s.execute(
        select(ultima.c.g, ultima.c.sq, ultima.c.ruolo).where(ultima.c.n == 1)
    )}
    giocatori = []
    for g in s.execute(select(Giocatore)).scalars():
        sq, ruolo = attuali.get(g.id, (None, None))
        giocatori.append(GiocatoreTrovato(
            g.id, g.nome, nomi_squadre.get(sq, ""), g.ruolo or ruolo or "", normalizza(g.nome)
        ))
    campionati: dict[int, set[int]] = {}
    for sq, comp in s.execute(
        select(Partita.casa_id, Partita.competizione_id).distinct()
        .union(select(Partita.trasferta_id, Partita.competizione_id).distinct())
    ):
        camp = campionato_di(comp)
        if camp is not None:
            campionati.setdefault(sq, set()).add(camp)
    squadre = [
        SquadraTrovata(sq, nome, frozenset(campionati.get(sq, ())), normalizza(nome))
        for sq, nome in nomi_squadre.items()
    ]
    return Indice(
        giocatori=tuple(sorted(giocatori, key=lambda x: x.norm)),
        squadre=tuple(sorted(squadre, key=lambda x: x.norm)),
    )


def _punteggio(norm: str, parole: list[str]) -> int | None:
    """None se non corrisponde; 0 se inizia con la ricerca, 1 se una parola inizia, 2 altrimenti."""
    if not all(p in norm for p in parole):
        return None
    if norm.startswith(parole[0]):
        return 0
    if any(w.startswith(parole[0]) for w in norm.split()):
        return 1
    return 2


def _trova(elementi, testo: str):
    parole = normalizza(testo).split()
    if not parole or len(normalizza(testo)) < MIN_CARATTERI:
        return []
    trovati = [(p, e) for e in elementi if (p := _punteggio(e.norm, parole)) is not None]
    trovati.sort(key=lambda x: (x[0], x[1].norm))
    return [e for _, e in trovati]


def cerca_giocatori(indice: Indice, testo: str) -> tuple[list[GiocatoreTrovato], int]:
    """(al massimo 20 giocatori, numero totale di corrispondenze)."""
    tutti = _trova(indice.giocatori, testo)
    return tutti[:MAX_RISULTATI], len(tutti)


def cerca_squadre(
    indice: Indice, testo: str, campionati: tuple[int, ...], tutti: bool = False
) -> tuple[list[SquadraTrovata], int]:
    """(al massimo 20 squadre dei campionati scelti, quante corrispondono ma sono di altri
    campionati). Con `tutti` nessun filtro."""
    trovate = _trova(indice.squadre, testo)
    if tutti:
        return trovate[:MAX_RISULTATI], 0
    scelte = [q for q in trovate if q.campionati & set(campionati)]
    return scelte[:MAX_RISULTATI], len(trovate) - len(scelte)


# ---------------------------------------------------------------- scheda del giocatore

@dataclass(frozen=True)
class RigaStagione:
    stagione: int
    competizione: str
    presenze: int
    minuti: int
    gialli: int
    rossi: int
    falli_commessi: int
    falli_subiti: int

    @property
    def gialli90(self) -> float | None:
        return per90(self.gialli, self.minuti)

    @property
    def falli90(self) -> float | None:
        return per90(self.falli_commessi, self.minuti)

    @property
    def subiti90(self) -> float | None:
        return per90(self.falli_subiti, self.minuti)


COLONNE_STAGIONI = (
    "Stagione", "Competizione", "Pres.", "Minuti", "Gialli", "Rossi",
    "Falli fatti", "Falli subiti", "Gialli/90'", "Falli/90'", "Subiti/90'",
)


def celle_stagione(r: RigaStagione) -> list[str]:
    return [
        str(r.stagione), r.competizione, str(r.presenze), str(r.minuti), str(r.gialli),
        str(r.rossi), str(r.falli_commessi), str(r.falli_subiti),
        testo_per90(r.gialli90), testo_per90(r.falli90), testo_per90(r.subiti90),
    ]


@dataclass(frozen=True)
class RigaUltima:
    data_ordinabile: datetime
    data: str
    avversario: str
    in_casa: bool
    minuti: int
    falli: int
    giallo: bool
    rosso: bool


COLONNE_ULTIME = ("Data", "Avversario", "Minuti", "Falli", "Cartellino")


def celle_ultima(r: RigaUltima) -> list[str]:
    cartellino = "🟥" if r.rosso else ("🟨" if r.giallo else "–")
    return [r.data, f"{'vs' if r.in_casa else '@'} {r.avversario}", str(r.minuti), str(r.falli), cartellino]


@dataclass(frozen=True)
class ProssimaPartita:
    partita_id: int
    quando: str
    avversario: str
    in_casa: bool
    candidato: Candidato | None  # None: non e' tra i candidati (formazioni non note)
    arbitro: str | None
    con_arbitro: tuple[int, int] | None  # (presenze, gialli) con l'arbitro designato
    storia: str
    derby: str | None


@dataclass(frozen=True)
class SchedaGiocatore:
    id: int
    nome: str
    squadra: str
    ruolo: str
    stagioni: list[RigaStagione]
    ultime: list[RigaUltima]
    diffidato: bool
    gialli_campionato: int
    prossima: ProssimaPartita | None


def _stagioni(s: Session, giocatore_id: int) -> list[RigaStagione]:
    righe = s.execute(
        select(
            Partita.stagione,
            Partita.competizione_id,
            func.sum(case((Presenza.minuti > 0, 1), else_=0)),
            func.sum(Presenza.minuti),
            func.sum(Presenza.gialli),
            func.sum(Presenza.rossi),
            func.sum(Presenza.falli_commessi),
            func.sum(Presenza.falli_subiti),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(Presenza.giocatore_id == giocatore_id)
        .group_by(Partita.stagione, Partita.competizione_id)
    ).all()
    righe.sort(key=lambda r: (-int(r[0]), _ORDINE_COMPETIZIONI.get(r[1], 99)))
    return [
        RigaStagione(
            int(st), NOMI_COMPETIZIONI.get(comp, str(comp)), _n(pres), _n(minuti), _n(gialli),
            _n(rossi), _n(fc), _n(fs),
        )
        for st, comp, pres, minuti, gialli, rossi, fc, fs in righe
    ]


def _ultime(s: Session, giocatore_id: int):
    """Le ultime partite con minuti o cartellini (anche dalla panchina)."""
    return s.execute(
        select(
            Partita.data_utc, Partita.casa_id, Partita.trasferta_id, Partita.competizione_id,
            Partita.stagione, Presenza.squadra_id, Presenza.minuti, Presenza.falli_commessi,
            Presenza.gialli, Presenza.rossi, Presenza.ruolo,
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id == giocatore_id,
            (Presenza.minuti > 0) | (Presenza.gialli > 0) | (Presenza.rossi > 0),
        )
        .order_by(Partita.data_utc.desc())
        .limit(ULTIME_PARTITE)
    ).all()


def _con_arbitro(s: Session, giocatore_id: int, arbitro_id: int, adesso: datetime) -> tuple[int, int]:
    """(presenze, gialli) del giocatore nelle partite passate dell'arbitro."""
    pres, gialli = s.execute(
        select(func.sum(case((Presenza.minuti > 0, 1), else_=0)), func.sum(Presenza.gialli))
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id == giocatore_id,
            Partita.arbitro_id == arbitro_id,
            Partita.data_utc < adesso,
        )
    ).one()
    return _n(pres), _n(gialli)


def _prossima(
    s: Session, giocatore: Giocatore, squadra_id: int, nomi: dict[int, str], adesso: datetime
) -> tuple[ProssimaPartita | None, Partita | None]:
    partita = s.execute(
        select(Partita)
        .where(
            (Partita.casa_id == squadra_id) | (Partita.trasferta_id == squadra_id),
            Partita.data_utc >= adesso,
            Partita.stato.not_in(("CANC", "PST")),
        )
        .order_by(Partita.data_utc)
        .limit(1)
    ).scalar_one_or_none()
    if partita is None:
        return None, None
    in_casa = partita.casa_id == squadra_id
    avv_id = partita.trasferta_id if in_casa else partita.casa_id
    avv_nome = nomi.get(avv_id) or s.get(Squadra, avv_id).nome

    candidato = next(
        (c for c in MercatoAmmonizioni().classifica(s, partita.id) if c.giocatore_id == giocatore.id),
        None,
    )

    arbitro = con_arbitro = None
    if partita.arbitro_id is not None:
        riga = s.get(Arbitro, partita.arbitro_id)
        arbitro = riga.nome_visualizzato if riga else None
        con_arbitro = _con_arbitro(s, giocatore.id, partita.arbitro_id, adesso)

    rivali = {
        d.squadra_b if d.squadra_a == squadra_id else d.squadra_a
        for d in rivalita.elenco_derby(s)
        if squadra_id in (d.squadra_a, d.squadra_b)
    }
    coppie = {(giocatore.id, avv_id)} | {(giocatore.id, r) for r in rivali}
    storie = componenti.storia_contro_batch(s, coppie, adesso)
    derby = None
    if rivali:
        nomi_rivali = {q.id: q.nome for q in s.execute(select(Squadra).where(Squadra.id.in_(rivali))).scalars()}
        pres = sum(storie[(giocatore.id, r)][0] for r in rivali)
        gialli = sum(storie[(giocatore.id, r)][1] for r in rivali)
        elenco = ", ".join(sorted(nomi_rivali.values()))
        derby = (
            f"Nei derby ({elenco}): nessun precedente nei dati" if pres == 0
            else f"Nei derby ({elenco}): {pres} partite, {gialli} gialli"
        )
    return (
        ProssimaPartita(
            partita_id=partita.id,
            quando=data_estesa(partita.data_utc),
            avversario=avv_nome,
            in_casa=in_casa,
            candidato=candidato,
            arbitro=arbitro,
            con_arbitro=con_arbitro,
            storia=componenti.testo_storia(*storie[(giocatore.id, avv_id)], avv_nome),
            derby=derby,
        ),
        partita,
    )


def scheda_giocatore(s: Session, giocatore_id: int, adesso: datetime) -> SchedaGiocatore | None:
    giocatore = s.get(Giocatore, giocatore_id)
    if giocatore is None:
        return None
    stagioni = _stagioni(s, giocatore_id)
    ultime = _ultime(s, giocatore_id)
    squadra_id = ultime[0].squadra_id if ultime else None
    if squadra_id is None:  # solo panchina senza cartellini: usa la presenza piu' recente
        squadra_id = s.execute(
            select(Presenza.squadra_id).join(Partita, Partita.id == Presenza.partita_id)
            .where(Presenza.giocatore_id == giocatore_id).order_by(Partita.data_utc.desc()).limit(1)
        ).scalar_one_or_none()
    ids = {u.casa_id for u in ultime} | {u.trasferta_id for u in ultime}
    if squadra_id is not None:
        ids.add(squadra_id)
    nomi = {
        q.id: q.nome for q in s.execute(select(Squadra).where(Squadra.id.in_(ids))).scalars()
    } if ids else {}

    prossima, partita = (
        _prossima(s, giocatore, squadra_id, nomi, adesso) if squadra_id is not None else (None, None)
    )

    # diffida: gialli del campionato (non delle coppe) nella stagione della prossima partita
    ultima_comp = ultime[0].competizione_id if ultime else None
    campionato = (
        (campionato_di(partita.competizione_id) if partita else None)
        or (campionato_di(ultima_comp) if ultima_comp else None)
        or SERIE_A
    )
    stagione = partita.stagione if partita else (ultime[0].stagione if ultime else STAGIONE_CORRENTE)
    nome_campionato = NOMI_COMPETIZIONI.get(campionato)
    gialli_campionato = sum(
        r.gialli for r in stagioni if r.stagione == stagione and r.competizione == nome_campionato
    )
    soglie = _soglie_diffida(campionato, carica_pesi(s))

    return SchedaGiocatore(
        id=giocatore.id,
        nome=giocatore.nome,
        squadra=nomi.get(squadra_id, ""),
        ruolo=giocatore.ruolo or (ultime[0].ruolo if ultime and ultime[0].ruolo else ""),
        stagioni=stagioni,
        ultime=[
            RigaUltima(
                u.data_utc,
                componenti.data_breve(u.data_utc),
                nomi.get(u.trasferta_id if u.squadra_id == u.casa_id else u.casa_id, ""),
                u.squadra_id == u.casa_id,
                _n(u.minuti), _n(u.falli_commessi), _n(u.gialli) > 0, _n(u.rossi) > 0,
            )
            for u in ultime
        ],
        diffidato=gialli_campionato in soglie,
        gialli_campionato=gialli_campionato,
        prossima=prossima,
    )


# ---------------------------------------------------------------- squadra

def partite_squadra(s: Session, squadra_id: int, adesso: datetime, giorni: int = GIORNI_SQUADRA):
    """Partite in programma della squadra nei prossimi `giorni` giorni (tutte le competizioni
    gestite), in ordine di data."""
    return componenti.prossime_partite(
        s, adesso, giorni=giorni, campionati=tuple(COMPETIZIONI.values()), squadra_id=squadra_id
    )
