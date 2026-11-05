"""Derby e campi caldi automatici (nessun inserimento a mano).

- Derby: elenco curato `config.DERBY_PREDEFINITI` per nome di squadra, risolto sugli id del
  database con la normalizzazione dei nomi di `caricamento.arbitri_fd`. In unione con le
  righe `ListaManuale` già presenti nel database.
- Campo caldo: la squadra in casa vede più cartellini del solito (vedi `campi_caldi_automatici`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.arbitri_fd import nome_squadra_normalizzato
from ammonizioni.config import (
    CAMPIONATI,
    CAMPO_CALDO_PARTITE_MINIME,
    CAMPO_CALDO_SOGLIA,
    CAMPO_CALDO_STAGIONI,
    DERBY_PREDEFINITI,
    NOMI_CAMPIONATI,
)
from ammonizioni.db.modelli import ListaManuale, Partita, Presenza, Squadra


def numero_it(valore: float, cifre: int = 1) -> str:
    """Numero con la virgola decimale: 5,1."""
    return f"{valore:.{cifre}f}".replace(".", ",")


@dataclass(frozen=True)
class Derby:
    squadra_a: int
    squadra_b: int
    nome_a: str
    nome_b: str
    campionato: int | None  # None: inserito a mano
    origine: str  # "predefinito" | "manuale"

    @property
    def coppia(self) -> frozenset[int]:
        return frozenset((self.squadra_a, self.squadra_b))

    @property
    def motivo(self) -> str:
        return f"Derby: {self.nome_a} – {self.nome_b}"


@dataclass(frozen=True)
class CampoCaldo:
    squadra_id: int
    nome: str
    partite: int  # partite casalinghe di campionato considerate
    cartellini_casa: float  # media di cartellini nelle sue partite in casa
    cartellini_lega: float  # media di cartellini del campionato
    origine: str = "automatico"  # "automatico" | "manuale"

    @property
    def motivo(self) -> str:
        if self.origine == "manuale":
            return f"{self.nome}: inserito a mano"
        return (
            f"{self.nome} in casa: {numero_it(self.cartellini_casa)} cartellini a partita "
            f"contro {numero_it(self.cartellini_lega)} di media"
        )


def _nomi_squadre(s: Session) -> dict[int, str]:
    return {i: n for i, n in s.execute(select(Squadra.id, Squadra.nome)).all()}


def _derby_manuali(s: Session, nomi: dict[int, str]) -> list[Derby]:
    righe = s.execute(
        select(ListaManuale.squadra_a_id, ListaManuale.squadra_b_id)
        .where(ListaManuale.tipo == "derby", ListaManuale.squadra_b_id.is_not(None))
        .order_by(ListaManuale.id)
    ).all()
    return [
        Derby(a, b, nomi.get(a, str(a)), nomi.get(b, str(b)), None, "manuale")
        for a, b in righe
    ]


def elenco_derby(s: Session) -> list[Derby]:
    """Derby riconosciuti: quelli predefiniti presenti nel database (nomi risolti con gli
    alias) e quelli inseriti a mano, senza doppioni (vince il predefinito)."""
    nomi = _nomi_squadre(s)
    per_nome: dict[str, list[int]] = {}
    for sid, nome in sorted(nomi.items()):
        per_nome.setdefault(nome_squadra_normalizzato(nome), []).append(sid)
    risultato: list[Derby] = []
    viste: set[frozenset[int]] = set()
    for campionato, coppie in DERBY_PREDEFINITI.items():
        for nome_a, nome_b in coppie:
            ids_a = per_nome.get(nome_squadra_normalizzato(nome_a), [])
            ids_b = per_nome.get(nome_squadra_normalizzato(nome_b), [])
            for a in ids_a:
                for b in ids_b:
                    if a == b or frozenset((a, b)) in viste:
                        continue
                    viste.add(frozenset((a, b)))
                    risultato.append(Derby(a, b, nomi[a], nomi[b], campionato, "predefinito"))
    for manuale in _derby_manuali(s, nomi):
        if manuale.coppia not in viste:
            viste.add(manuale.coppia)
            risultato.append(manuale)
    return risultato


def derby_noti(s: Session) -> set[frozenset[int]]:
    """Coppie di squadre in rivalità (predefinite e manuali) per il motore."""
    return {d.coppia for d in elenco_derby(s)}


def campi_caldi_automatici(
    s: Session, stagione: int, prima_di: datetime
) -> dict[int, CampoCaldo]:
    """Squadre con il "campo caldo": nelle partite casalinghe di campionato (finite, con
    statistiche) delle ultime `CAMPO_CALDO_STAGIONI` stagioni fino a `stagione`, prima di
    `prima_di`, la media di cartellini (gialli + rossi, entrambe le squadre) supera di almeno
    il 20% quella del campionato, con almeno 15 partite casalinghe. Una sola query
    raggruppata; i totali sono convertiti da Decimal (Postgres) a numeri Python."""
    per_partita = (
        select(
            Presenza.partita_id.label("partita_id"),
            func.sum(Presenza.gialli + Presenza.rossi).label("cartellini"),
        )
        .group_by(Presenza.partita_id)
        .subquery()
    )
    righe = s.execute(
        select(
            Partita.competizione_id,
            Partita.casa_id,
            func.count(),
            func.sum(per_partita.c.cartellini),
        )
        .join(per_partita, per_partita.c.partita_id == Partita.id)
        .where(
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.statistiche_scaricate.is_(True),
            Partita.data_utc < prima_di,
            Partita.stagione <= stagione,
            Partita.stagione > stagione - CAMPO_CALDO_STAGIONI,
        )
        .group_by(Partita.competizione_id, Partita.casa_id)
    ).all()

    lega: dict[int, list[float]] = {}  # campionato -> [partite, cartellini]
    casalinghe: list[tuple[int, int, int, float]] = []
    for competizione, casa, n, totale in righe:
        n, totale = int(n), float(totale or 0)
        acc = lega.setdefault(competizione, [0, 0.0])
        acc[0] += n
        acc[1] += totale
        casalinghe.append((competizione, casa, n, totale))

    candidate = {}
    for competizione, casa, n, totale in casalinghe:
        partite_lega, cartellini_lega = lega[competizione]
        if n < CAMPO_CALDO_PARTITE_MINIME or partite_lega == 0 or cartellini_lega <= 0:
            continue
        media_casa = totale / n
        media_lega = cartellini_lega / partite_lega
        if media_casa >= media_lega * CAMPO_CALDO_SOGLIA:
            candidate[casa] = (n, media_casa, media_lega)
    if not candidate:
        return {}
    nomi = dict(
        s.execute(select(Squadra.id, Squadra.nome).where(Squadra.id.in_(candidate))).all()
    )
    return {
        casa: CampoCaldo(casa, nomi.get(casa, str(casa)), n, media_casa, media_lega)
        for casa, (n, media_casa, media_lega) in candidate.items()
    }


def campi_caldi_manuali(s: Session) -> set[int]:
    return set(
        s.execute(
            select(ListaManuale.squadra_a_id).where(ListaManuale.tipo == "campo_caldo")
        ).scalars()
    )


def campi_caldi_noti(s: Session, stagione: int, prima_di: datetime) -> set[int]:
    """Id delle squadre con il campo caldo (automatico o inserito a mano) per il motore."""
    return set(campi_caldi_automatici(s, stagione, prima_di)) | campi_caldi_manuali(s)


def elenco_campi_caldi(s: Session, stagione: int, prima_di: datetime) -> list[CampoCaldo]:
    """Campi caldi con il motivo: automatici (dal più caldo) e poi quelli inseriti a mano."""
    auto = campi_caldi_automatici(s, stagione, prima_di)
    risultato = sorted(auto.values(), key=lambda c: -c.cartellini_casa / c.cartellini_lega)
    manuali = [i for i in campi_caldi_manuali(s) if i not in auto]
    if manuali:
        nomi = dict(
            s.execute(select(Squadra.id, Squadra.nome).where(Squadra.id.in_(manuali))).all()
        )
        risultato.extend(
            CampoCaldo(i, nomi.get(i, str(i)), 0, 0.0, 0.0, "manuale") for i in sorted(manuali)
        )
    return risultato


def nome_campionato(campionato: int | None) -> str:
    return NOMI_CAMPIONATI.get(campionato, "") if campionato is not None else ""
