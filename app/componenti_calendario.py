"""Logica della pagina Calendario (senza Streamlit): le giornate di un campionato nella
stagione corrente, la giornata in corso e le partite di una giornata.

Se i dati non hanno il numero di giornata (la fonte ESPN non lo dà: arriva da football-data)
le partite si dividono per settimana, da lunedì a domenica, ora di Roma."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.config import STAGIONE_CORRENTE, STATI_FINITI
from ammonizioni.db.modelli import Partita

# Stati che non aspettano piu' un risultato (finite, rinviate, annullate): una giornata con
# solo partite cosi' e' "passata" anche se una e' stata rinviata a data da destinarsi.
STATI_CHIUSI = (*STATI_FINITI, "CANC", "PST")


@dataclass(frozen=True)
class Turno:
    """Una giornata (o una settimana, se mancano i numeri di giornata)."""
    chiave: int  # numero di giornata; per le settimane il lunedì (date.toordinal())
    etichetta: str
    ids: tuple[int, ...]
    finito: bool
    inizio: datetime  # partita più vicina all'inizio


@dataclass(frozen=True)
class Calendario:
    per_giornata: bool
    turni: tuple[Turno, ...]  # in ordine cronologico
    in_corso: int | None  # indice in `turni`: la prima con partite non chiuse, altrimenti l'ultima

    def indice(self, chiave: int | None) -> int | None:
        """Indice del turno con quella chiave; se manca (o è None) quello in corso."""
        for i, t in enumerate(self.turni):
            if t.chiave == chiave:
                return i
        return self.in_corso


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _giornate_complete(
    partite: list[tuple[int, int | None, datetime, str]],
) -> list[int | None]:
    """Giornata di ogni partita (nell'ordine dato): quelle mancanti prendono la giornata della
    partita con giornata più vicina nel tempo (prima la precedente). Tutte None se nessuna ce l'ha."""
    note = sorted((_utc(d), g) for _, g, d, _ in partite if g is not None)
    if not note:
        return [None] * len(partite)
    date_note = [d for d, _ in note]
    risultato: list[int | None] = []
    for _, g, d, _ in partite:
        if g is not None:
            risultato.append(g)
            continue
        i = bisect_right(date_note, _utc(d))
        risultato.append(note[i - 1][1] if i > 0 else note[0][1])
    return risultato


def _etichetta_settimana(lunedi: date) -> str:
    domenica = lunedi + timedelta(days=6)
    fine = f"{domenica.day} {componenti.MESI[domenica.month - 1]} {domenica.year}"
    if lunedi.month == domenica.month:
        inizio = f"{lunedi.day}"
    elif lunedi.year == domenica.year:
        inizio = f"{lunedi.day} {componenti.MESI[lunedi.month - 1]}"
    else:
        inizio = f"{lunedi.day} {componenti.MESI[lunedi.month - 1]} {lunedi.year}"
    return f"Settimana dal {inizio} al {fine}"


def costruisci_calendario(partite: list[tuple[int, int | None, datetime, str]]) -> Calendario:
    """Calendario da (id, giornata, data_utc, stato) di tutte le partite del campionato nella
    stagione: giornate se almeno una partita ha il numero, altrimenti settimane."""
    if not partite:
        return Calendario(per_giornata=True, turni=(), in_corso=None)
    giornate = _giornate_complete(partite)
    per_giornata = any(g is not None for g in giornate)
    gruppi: dict[int, list[tuple[int, datetime, str]]] = {}
    for (pid, _, data, stato), g in zip(partite, giornate):
        data = _utc(data)
        if per_giornata:
            chiave = g
        else:
            locale = data.astimezone(componenti.ROMA).date()
            chiave = (locale - timedelta(days=locale.weekday())).toordinal()
        gruppi.setdefault(chiave, []).append((pid, data, stato))
    turni = []
    for chiave, voci in gruppi.items():
        voci.sort(key=lambda v: (v[1], v[0]))
        etichetta = (
            f"Giornata {chiave}" if per_giornata else _etichetta_settimana(date.fromordinal(chiave))
        )
        turni.append(Turno(
            chiave=chiave,
            etichetta=etichetta,
            ids=tuple(v[0] for v in voci),
            finito=all(v[2] in STATI_CHIUSI for v in voci),
            inizio=voci[0][1],
        ))
    turni.sort(key=lambda t: t.chiave)  # giornate e lunedì (ordinale) crescono col tempo
    in_corso = next((i for i, t in enumerate(turni) if not t.finito), len(turni) - 1)
    return Calendario(per_giornata=per_giornata, turni=tuple(turni), in_corso=in_corso)


def carica_calendario(
    s: Session, campionato: int, stagione: int = STAGIONE_CORRENTE
) -> Calendario:
    """Una sola query leggera per tutte le partite del campionato nella stagione."""
    righe = s.execute(
        select(Partita.id, Partita.giornata, Partita.data_utc, Partita.stato)
        .where(Partita.competizione_id == campionato, Partita.stagione == stagione)
        .order_by(Partita.data_utc, Partita.id)
    ).all()
    return costruisci_calendario([tuple(r) for r in righe])


def righe_turno(s: Session, ids: tuple[int, ...]) -> list[componenti.RigaPartita]:
    """Righe per le schede delle partite di un turno (poche query raggruppate)."""
    if not ids:
        return []
    partite = s.execute(select(Partita).where(Partita.id.in_(ids))).scalars().all()
    return componenti.righe_partite(s, list(partite))


def sottotitolo(righe: list[componenti.RigaPartita]) -> str:
    """"12 partite · 3 giocate" sotto il titolo del turno."""
    giocate = sum(1 for r in righe if r.finita)
    testo = f"{len(righe)} partita" if len(righe) == 1 else f"{len(righe)} partite"
    if giocate:
        testo += " · 1 giocata" if giocate == 1 else f" · {giocate} giocate"
    return testo
