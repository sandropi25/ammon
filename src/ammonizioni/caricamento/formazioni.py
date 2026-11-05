"""Formazioni: ultimo XI di una squadra, formazioni probabili e riepilogo dei cambi."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from ammonizioni.config import CAMPIONATI, SOGLIE_DIFFIDA
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza
from ammonizioni.motore.tipi import RUOLI, Titolare


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
        select(Presenza, Giocatore, Formazione.griglia)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .outerjoin(
            Formazione,
            (Formazione.partita_id == Presenza.partita_id)
            & (Formazione.squadra_id == Presenza.squadra_id)
            & (Formazione.giocatore_id == Presenza.giocatore_id)
            & (Formazione.tipo == "ufficiale"),
        )
        .where(
            Presenza.partita_id == ultima,
            Presenza.squadra_id == squadra_id,
            Presenza.titolare.is_(True),
        )
        .order_by(Giocatore.id)
    ).all()
    # griglia della presenza, altrimenti quella della formazione ufficiale di quella partita
    return [
        titolare_da(g, squadra_id, p.griglia or griglia_ufficiale, p.ruolo)
        for p, g, griglia_ufficiale in righe
    ]


def salva_probabili(
    s: Session,
    partita_id: int,
    titolari_per_squadra: dict[int, list[int]],
    griglie: dict[int, str | None] | None = None,
) -> None:
    """Sostituisce le formazioni probabili della partita (le ufficiali restano).
    `griglie` (giocatore_id -> griglia) conserva le posizioni dell'ultimo XI, che servono
    a trovare l'avversario diretto prima delle formazioni ufficiali."""
    griglie = griglie or {}
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
                    griglia=griglie.get(giocatore_id),
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


# --- formazioni probabili calcolate ---------------------------------------------

PARTITE_PER_PROBABILI = 5
TITOLARI = 11
_RIGA_DA_RUOLO = {"G": 1, "D": 2, "M": 3, "F": 5}
_RUOLO_DA_RIGA = {1: "G", 2: "D", 3: "M", 4: "M", 5: "F"}


def _riga_colonna(griglia: str | None, ruolo: str | None) -> tuple[int, int | None]:
    """(riga, colonna) dalla griglia "riga:colonna"; senza griglia la riga viene dal ruolo."""
    try:
        riga, colonna = griglia.split(":")  # type: ignore[union-attr]
        return int(riga), int(colonna)
    except (AttributeError, ValueError):
        return _RIGA_DA_RUOLO.get(ruolo or "", 3), None


def _squalificati(
    s: Session, squadra_id: int, ultima: tuple[int, int, int, datetime]
) -> set[int]:
    """Giocatori della squadra che l'ultima partita di campionato lascia squalificati:
    rosso, oppure ammonizione (anche dalla panchina) che porta i gialli del campionato nella
    stagione oltre una soglia di `SOGLIE_DIFFIDA` (soglia + 1)."""
    partita_id, campionato, stagione, data = ultima
    righe = s.execute(
        select(Presenza.giocatore_id, Presenza.rossi, Presenza.gialli).where(
            Presenza.partita_id == partita_id,
            Presenza.squadra_id == squadra_id,
            (Presenza.rossi > 0) | (Presenza.gialli > 0),
        )
    ).all()
    sospesi = {g for g, rossi, _ in righe if int(rossi) > 0}
    ammoniti = [g for g, rossi, gialli in righe if int(rossi) == 0 and int(gialli) > 0]
    soglie = SOGLIE_DIFFIDA.get(campionato, ())
    if ammoniti and soglie:
        totali = s.execute(
            select(
                Presenza.giocatore_id,
                func.sum(Presenza.gialli),
                func.sum(case((Presenza.partita_id == partita_id, Presenza.gialli), else_=0)),
            )
            .join(Partita, Partita.id == Presenza.partita_id)
            .where(
                Presenza.giocatore_id.in_(ammoniti),
                Partita.competizione_id == campionato,
                Partita.stagione == stagione,
                Partita.data_utc <= data,
            )
            .group_by(Presenza.giocatore_id)
        ).all()
        for giocatore_id, totale, ultima_volta in totali:
            # Postgres restituisce Decimal per le somme: sempre int
            totale = int(totale or 0)
            prima = totale - int(ultima_volta or 0)
            if any(prima <= soglia < totale for soglia in soglie):
                sospesi.add(giocatore_id)
    return sospesi


def probabili_automatiche(s: Session, squadra_id: int, prima_di: datetime) -> list[Titolare]:
    """Formazione probabile calcolata dalle ultime 5 partite di campionato della squadra:
    il modulo più usato (titolari per riga della griglia); per ogni posto il giocatore che
    ci ha giocato più spesso (a pari merito quello più usato nella riga); gli squalificati
    noti (rosso, o gialli che superano una soglia di diffida nell'ultima partita) sono
    esclusi e sostituiti dal più usato dello stesso ruolo. Griglia sintetica "riga:colonna".
    Lista vuota senza partite di campionato con titolari: allora si usa `ultimo_xi`."""
    ultime = [
        (int(p), int(c), int(st), d)
        for p, c, st, d in s.execute(
            select(Partita.id, Partita.competizione_id, Partita.stagione, Partita.data_utc)
            .join(Presenza, Presenza.partita_id == Partita.id)
            .where(
                Presenza.squadra_id == squadra_id,
                Presenza.titolare.is_(True),
                Partita.competizione_id.in_(CAMPIONATI),
                Partita.data_utc < prima_di,
            )
            .distinct()
            .order_by(Partita.data_utc.desc())
            .limit(PARTITE_PER_PROBABILI)
        ).all()
    ]
    if not ultime:
        return []
    posizione = {p: i for i, (p, _, _, _) in enumerate(ultime)}  # 0 = la più recente
    righe = s.execute(
        select(Presenza.partita_id, Presenza.ruolo, Presenza.griglia, Giocatore)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(
            Presenza.partita_id.in_(list(posizione)),
            Presenza.squadra_id == squadra_id,
            Presenza.titolare.is_(True),
        )
        .order_by(Giocatore.id)
    ).all()
    per_partita: dict[int, list[tuple[int, int | None, str | None, Giocatore]]] = {}
    for partita_id, ruolo, griglia, g in righe:
        riga, colonna = _riga_colonna(griglia, ruolo)
        per_partita.setdefault(partita_id, []).append((riga, colonna, ruolo or g.ruolo, g))
    # solo le partite con undici titolari; il modulo è il numero di titolari per riga
    complete = [p for p, _, _, _ in ultime if len(per_partita.get(p, [])) == TITOLARI]
    if not complete:
        return []
    firme = {
        p: tuple(sorted(Counter(r for r, _, _, _ in per_partita[p]).items())) for p in complete
    }
    frequenze = Counter(firme.values())
    # il più frequente; a pari merito quello usato più di recente (`complete` è dal più recente)
    modulo = max((firme[p] for p in complete), key=lambda f: frequenze[f])
    posti = [(riga, colonna) for riga, n in modulo for colonna in range(1, n + 1)]

    sospesi = _squalificati(s, squadra_id, ultime[0])

    giocatori: dict[int, Giocatore] = {}
    corsia: dict[tuple[int, int], Counter] = {}
    nella_riga: dict[int, Counter] = {}
    ultima_volta: dict[tuple[int, int], int] = {}
    ruolo_riga: dict[tuple[int, int], Counter] = {}
    in_totale: Counter = Counter()
    ruolo_giocatore: dict[int, str] = {}
    for p in complete:
        for riga, colonna, ruolo, g in per_partita[p]:
            giocatori[g.id] = g
            nella_riga.setdefault(riga, Counter())[g.id] += 1
            in_totale[g.id] += 1
            ultima_volta[(g.id, riga)] = min(ultima_volta.get((g.id, riga), 99), posizione[p])
            if ruolo in RUOLI:
                ruolo_riga.setdefault((g.id, riga), Counter())[ruolo] += 1
                ruolo_giocatore.setdefault(g.id, ruolo)
            if firme[p] == modulo and colonna is not None:
                corsia.setdefault((riga, colonna), Counter())[g.id] += 1

    assegnati: dict[tuple[int, int], int] = {}
    presi: set[int] = set()
    # prima i posti con una corsia chiara (chi ci ha giocato di più), poi il resto per riga
    candidati_corsia = sorted(
        (-n, posto, g_id)
        for posto, conteggio in corsia.items()
        if posto in posti
        for g_id, n in conteggio.items()
        if g_id not in sospesi
    )
    for _, posto, g_id in candidati_corsia:
        if posto not in assegnati and g_id not in presi:
            assegnati[posto] = g_id
            presi.add(g_id)
    for posto in posti:
        if posto in assegnati:
            continue
        riga = posto[0]
        liberi = [g for g in nella_riga.get(riga, {}) if g not in sospesi and g not in presi]
        if not liberi:  # nessuno in quella riga: il più usato dello stesso ruolo
            ruolo = _RUOLO_DA_RIGA.get(riga, "M")
            liberi = [
                g for g in in_totale
                if g not in sospesi and g not in presi and ruolo_giocatore.get(g) == ruolo
            ]
        if not liberi:
            continue
        scelto = min(
            liberi,
            key=lambda g: (
                -nella_riga.get(riga, Counter())[g], -in_totale[g],
                ultima_volta.get((g, riga), 99), g,
            ),
        )
        assegnati[posto] = scelto
        presi.add(scelto)

    risultato = []
    for riga, colonna in posti:
        g_id = assegnati.get((riga, colonna))
        if g_id is None:
            continue
        ruoli = ruolo_riga.get((g_id, riga))
        ruolo = ruoli.most_common(1)[0][0] if ruoli else _RUOLO_DA_RIGA.get(riga)
        risultato.append(titolare_da(giocatori[g_id], squadra_id, f"{riga}:{colonna}", ruolo))
    return risultato
