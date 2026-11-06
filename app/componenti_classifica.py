"""Logica della pagina Classifica (senza Streamlit): classifica dei campionati calcolata dai
risultati nel database (nessuna richiesta esterna), con forma, zone e cartellini a partita.

Criteri a parità di punti: differenza reti, gol fatti, poi nome. Gli scontri diretti, che la
Serie A usa per primi, NON sono applicati: a parità di punti l'ordine può differire da quello
ufficiale.

Ogni cartellino conta, anche quelli presi dalla panchina: i gialli e i rossi della squadra
sono la somma di tutte le sue presenze nelle partite con statistiche. Tre query raggruppate
per tutti i campionati chiesti; su Postgres SUM e COUNT restituiscono Decimal, quindi ogni
aggregato è convertito in int."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.config import (
    NOMI_CAMPIONATI,
    RETROCESSE,
    STAGIONE_CORRENTE,
    STATI_FINITI,
    ZONE_CLASSIFICA,
)
from ammonizioni.db.modelli import Partita, Presenza, Squadra

PARTITE_FORMA = 5
VITTORIA, PAREGGIO, SCONFITTA = "V", "N", "P"
NOMI_ESITI = {VITTORIA: "Vittoria", PAREGGIO: "Pareggio", SCONFITTA: "Sconfitta"}
NOMI_ZONE = {
    "champions": "Champions League",
    "europa": "Europa League",
    "conference": "Conference League",
    "retrocessione": "Retrocessione",
}
NOTA_CRITERI = (
    "A parità di punti: differenza reti, gol fatti, poi nome. Gli scontri diretti "
    "(primo criterio in Serie A) non sono applicati."
)


@dataclass(frozen=True)
class RigaTabella:
    posizione: int
    squadra_id: int
    nome: str
    logo: str | None
    punti: int
    giocate: int
    vinte: int
    pari: int
    perse: int
    gol_fatti: int
    gol_subiti: int
    # ultime partite, dalla meno recente alla più recente: (esito V/N/P, descrizione)
    forma: tuple[tuple[str, str], ...]
    gialli: int  # tutti, anche dalla panchina
    rossi: int
    partite_cartellini: int  # partite finite con le statistiche dei cartellini
    zona: str | None = None

    @property
    def differenza(self) -> int:
        return self.gol_fatti - self.gol_subiti

    @property
    def gialli_partita(self) -> float | None:
        return self.gialli / self.partite_cartellini if self.partite_cartellini else None

    @property
    def rossi_partita(self) -> float | None:
        return self.rossi / self.partite_cartellini if self.partite_cartellini else None


@dataclass(frozen=True)
class Classifica:
    campionato: int
    nome: str
    stagione: int
    righe: tuple[RigaTabella, ...]

    @property
    def zone(self) -> tuple[str, ...]:
        """Zone presenti nella classifica, nell'ordine della tabella (per la legenda)."""
        viste: list[str] = []
        for r in self.righe:
            if r.zona and r.zona not in viste:
                viste.append(r.zona)
        return tuple(viste)


def zona_di(posizione: int, squadre: int, campionato: int) -> str | None:
    """Zona della posizione: europea (dalla configurazione) o retrocessione (le ultime N).
    Con poche squadre le zone europee hanno la precedenza sulla retrocessione."""
    europee = ZONE_CLASSIFICA.get(campionato, ())
    for nome, da, a in europee:
        if da <= posizione <= a:
            return nome
    ultima_europea = max((a for _, _, a in europee), default=0)
    retrocesse = RETROCESSE.get(campionato, 0)
    if retrocesse and posizione > max(squadre - retrocesse, ultima_europea):
        return "retrocessione"
    return None


def _esito(fatti: int, subiti: int) -> str:
    return VITTORIA if fatti > subiti else PAREGGIO if fatti == subiti else SCONFITTA


def calcola_classifica(
    campionato: int,
    risultati: list[tuple[datetime, int, int, int, int]],
    squadre: dict[int, tuple[str, str | None]],
    cartellini: dict[int, tuple[int, int, int]] | None = None,
    stagione: int = STAGIONE_CORRENTE,
) -> Classifica:
    """Classifica dai risultati (data, casa, trasferta, gol casa, gol trasferta) delle partite
    finite. `squadre` (id -> (nome, logo)) contiene anche chi non ha ancora giocato;
    `cartellini` id -> (gialli, rossi, partite con statistiche)."""
    cartellini = cartellini or {}
    nomi = {sq: v[0] for sq, v in squadre.items()}
    conti: dict[int, dict[str, int]] = {}
    forma: dict[int, list[tuple[str, str]]] = {}
    for sq in squadre:
        conti[sq] = dict(v=0, n=0, p=0, gf=0, gs=0)
        forma[sq] = []
    for _data, casa, trasf, gc, gt in sorted(risultati, key=lambda r: r[0]):
        for sq, avv, gf, gs, dove in ((casa, trasf, gc, gt, "in casa"), (trasf, casa, gt, gc, "in trasferta")):
            c = conti.setdefault(sq, dict(v=0, n=0, p=0, gf=0, gs=0))
            esito = _esito(gf, gs)
            c[{VITTORIA: "v", PAREGGIO: "n", SCONFITTA: "p"}[esito]] += 1
            c["gf"] += gf
            c["gs"] += gs
            testo = f"{NOMI_ESITI[esito]} {gf}–{gs} con {nomi.get(avv, '?')} ({dove})"
            forma.setdefault(sq, []).append((esito, testo))

    def chiave(sq: int):
        c = conti[sq]
        punti = 3 * c["v"] + c["n"]
        return (-punti, -(c["gf"] - c["gs"]), -c["gf"], nomi.get(sq, "").casefold(), sq)

    ordine = sorted(conti, key=chiave)
    righe = []
    for pos, sq in enumerate(ordine, start=1):
        c = conti[sq]
        gialli, rossi, partite = cartellini.get(sq, (0, 0, 0))
        nome, logo = squadre.get(sq, ("?", None))
        righe.append(
            RigaTabella(
                posizione=pos, squadra_id=sq, nome=nome, logo=logo,
                punti=3 * c["v"] + c["n"], giocate=c["v"] + c["n"] + c["p"],
                vinte=c["v"], pari=c["n"], perse=c["p"], gol_fatti=c["gf"], gol_subiti=c["gs"],
                forma=tuple(forma[sq][-PARTITE_FORMA:]),
                gialli=gialli, rossi=rossi, partite_cartellini=partite,
                zona=zona_di(pos, len(ordine), campionato),
            )
        )
    return Classifica(
        campionato=campionato, nome=NOMI_CAMPIONATI.get(campionato, str(campionato)),
        stagione=stagione, righe=tuple(righe),
    )


# ---------------------------------------------------------------- query raggruppate

def _partite(s: Session, campionati: tuple[int, ...], stagione: int):
    """Tutte le partite dei campionati nella stagione (anche future: servono le squadre)."""
    return s.execute(
        select(
            Partita.competizione_id, Partita.data_utc, Partita.casa_id, Partita.trasferta_id,
            Partita.gol_casa, Partita.gol_trasferta, Partita.stato,
        ).where(Partita.competizione_id.in_(campionati), Partita.stagione == stagione)
    ).all()


def _cartellini(
    s: Session, campionati: tuple[int, ...], stagione: int
) -> dict[tuple[int, int], tuple[int, int, int]]:
    """(campionato, squadra) -> (gialli, rossi, partite) delle partite finite con statistiche:
    tutte le presenze, anche i gialli dalla panchina. Aggregati convertiti in int."""
    righe = s.execute(
        select(
            Partita.competizione_id, Presenza.squadra_id,
            func.sum(Presenza.gialli), func.sum(Presenza.rossi),
            func.count(func.distinct(Presenza.partita_id)),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Partita.competizione_id.in_(campionati),
            Partita.stagione == stagione,
            Partita.stato.in_(STATI_FINITI),
            Partita.statistiche_scaricate.is_(True),
        )
        .group_by(Partita.competizione_id, Presenza.squadra_id)
    ).all()
    return {
        (int(comp), int(sq)): (int(gialli or 0), int(rossi or 0), int(partite or 0))
        for comp, sq, gialli, rossi, partite in righe
    }


def carica_classifiche(
    s: Session, campionati: tuple[int, ...], stagione: int = STAGIONE_CORRENTE
) -> tuple[Classifica, ...]:
    """Classifiche dei campionati dati (nell'ordine dato), con poche query raggruppate
    qualunque sia il numero di campionati e di squadre."""
    campionati = tuple(campionati)
    if not campionati:
        return ()
    partite = _partite(s, campionati, stagione)
    cartellini = _cartellini(s, campionati, stagione)
    ids = {sq for p in partite for sq in (p[2], p[3])}
    anagrafica = (
        s.execute(select(Squadra.id, Squadra.nome, Squadra.logo_url).where(Squadra.id.in_(ids))).all()
        if ids else []
    )
    immagini = componenti.immagini_attive(s) if ids else False
    dati = {
        sq: (nome, componenti.url_https(logo) if immagini else None)
        for sq, nome, logo in anagrafica
    }
    risultato = []
    for camp in campionati:
        sue = [p for p in partite if p[0] == camp]
        squadre = {
            sq: dati.get(sq, ("?", None)) for p in sue for sq in (p[2], p[3])
        }
        risultati = [
            (d, c, t, int(gc), int(gt))
            for _, d, c, t, gc, gt, stato in sue
            if stato in STATI_FINITI and gc is not None and gt is not None
        ]
        suoi_cartellini = {sq: v for (cc, sq), v in cartellini.items() if cc == camp}
        risultato.append(calcola_classifica(camp, risultati, squadre, suoi_cartellini, stagione))
    return tuple(risultato)


def media(valore: float | None) -> str:
    """Media a partita con la virgola ("2,35"); "–" senza dati."""
    return "–" if valore is None else f"{valore:.2f}".replace(".", ",")


def differenza(valore: int) -> str:
    return f"+{valore}" if valore > 0 else str(valore)
