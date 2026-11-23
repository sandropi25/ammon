"""Formazione ufficiale incollata dall'utente, col testo dei giornali, quando ESPN e' in ritardo.

I club pubblicano le ufficiali circa 60 minuti prima, ESPN 37-46 minuti prima (misurato il
21-22/11/2026). Dall'app si incolla il testo di una squadra, per esempio
"ATALANTA (4-2-3-1): Carnesecchi; Bellanova, Scalvini, Kolasinac, Zappacosta; Kessie, Ederson;
Elmas, De Ketelaere, Zalewski; Krstovic. All. Sarri": le linee separate dal ";" diventano le
righe del campo, i nomi si cercano tra i giocatori della squadra."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza

TITOLARI = 11
# righe della griglia (1..5) per le linee di movimento, come per i ruoli generici di ESPN
RIGHE_PER_LINEE = {2: (2, 5), 3: (2, 3, 5), 4: (2, 3, 4, 5), 5: (2, 3, 4, 4, 5)}
RIGA_DA_RUOLO = {"G": 1, "D": 2, "M": 3, "F": 5}

_TAGLI = (
    r"\b(?:a\s+disp(?:osizione)?|in\s+panchina|panchina)\b.*",  # la panchina, fino in fondo
    r"\ball(?:\.|enatore\b).*",  # l'allenatore, fino in fondo
)


def _normale(testo: str) -> str:
    return unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode().lower()


def leggi_testo(testo: str) -> list[list[str]]:
    """Le linee della formazione (dal portiere all'attacco), ognuna con i nomi da destra a
    sinistra come li scrivono i giornali. Toglie squadra, modulo, numeri di maglia,
    panchina e allenatore. Senza ";" ogni riga del testo e' una linea."""
    pulito = testo.replace("\r", "")
    for taglio in _TAGLI:
        pulito = re.sub(taglio, "", pulito, flags=re.I | re.S)
    pulito = re.sub(r"\([^)]*\)", " ", pulito)  # "(4-2-3-1)"
    # "ATALANTA:" o "Inter 3-5-2:" in testa: tutto quello che precede i due punti
    pulito = re.sub(r"^\s*[^:;,\n]*:\s*", "", pulito)
    pulito = pulito.replace("\n", ";") if ";" not in pulito else pulito.replace("\n", " ")
    linee = []
    for pezzo in pulito.split(";"):
        nomi = []
        for nome in re.split(r",|\s[-–]\s", pezzo):
            nome = re.sub(r"^\s*\d+\s*", "", nome).strip().rstrip(".").strip()
            if nome and not re.fullmatch(r"[\d\s-]+", nome):
                nomi.append(nome)
        if nomi:
            linee.append(nomi)
    return linee


@dataclass
class Lettura:
    titolari: list[tuple[int, str]] = field(default_factory=list)  # (giocatore_id, griglia)
    mancanti: list[str] = field(default_factory=list)  # nomi non trovati nella squadra
    ambigui: list[tuple[str, list[tuple[int, str]]]] = field(default_factory=list)
    nomi: dict[int, str] = field(default_factory=dict)  # come si chiamano nel database

    @property
    def pronta(self) -> bool:
        return len(self.titolari) == TITOLARI and not self.mancanti and not self.ambigui


def _rosa(s: Session, partita: Partita, squadra_id: int) -> list[tuple[int, str, str | None]]:
    """Giocatori della squadra: presenze di questa stagione e della precedente prima della
    partita, piu' le formazioni gia' salvate per la partita. Dal piu' recente."""
    recenti = s.execute(
        select(Giocatore.id, Giocatore.nome, Giocatore.ruolo, func.max(Partita.data_utc))
        .join(Presenza, Presenza.giocatore_id == Giocatore.id)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.squadra_id == squadra_id,
            Partita.stagione >= partita.stagione - 1,
            Partita.data_utc < partita.data_utc,
        )
        .group_by(Giocatore.id, Giocatore.nome, Giocatore.ruolo)
        .order_by(func.max(Partita.data_utc).desc())
    ).all()
    rosa = {gid: (gid, nome, ruolo) for gid, nome, ruolo, _ in recenti}
    for gid, nome, ruolo in s.execute(
        select(Giocatore.id, Giocatore.nome, Giocatore.ruolo)
        .join(Formazione, Formazione.giocatore_id == Giocatore.id)
        .where(Formazione.partita_id == partita.id, Formazione.squadra_id == squadra_id)
    ).all():
        rosa.setdefault(gid, (gid, nome, ruolo))
    return list(rosa.values())


def _candidati(testo: str, rosa: list[tuple[int, str, str | None]]) -> list[tuple[int, str, str | None]]:
    """Giocatori della rosa che corrispondono al nome scritto: tutte le parole del cognome e,
    se c'e', l'iniziale del nome ("J. Martinez", "Martinez J.", "Le. Colombo")."""
    iniziali, parole = [], []
    for pezzo in testo.replace(".", ". ").split():
        p = _normale(pezzo.strip())
        if not p.rstrip("."):
            continue
        (iniziali if p.endswith(".") or len(p) == 1 else parole).append(p.rstrip("."))
    if not parole:
        return []
    trovati = []
    for voce in rosa:
        nome = _normale(voce[1]).replace("-", " ").split()
        if not all(p in nome for p in parole):
            continue
        resto = [n for n in nome if n not in parole] or nome
        if iniziali and not any(n.startswith(i) for i in iniziali for n in resto):
            continue
        trovati.append(voce)
    return trovati


def riconosci(
    s: Session, partita: Partita, squadra_id: int, testo: str,
    scelte: dict[str, int] | None = None,
) -> Lettura:
    """Legge il testo incollato e trova i giocatori della squadra con la loro griglia.
    `scelte` (nome scritto -> giocatore_id) risolve a mano gli omonimi."""
    scelte = scelte or {}
    rosa = _rosa(s, partita, squadra_id)
    linee = leggi_testo(testo)
    lettura = Lettura()
    ruoli: dict[int, str | None] = {}
    linee_id: list[list[int]] = []
    # chi e' gia' riconosciuto senza dubbi non puo' essere anche un altro nome del testo
    sicuri = {
        trovati[0][0]
        for linea in linee for scritto in linea
        if len(trovati := _candidati(scritto, rosa)) == 1
    }
    for linea in linee:
        ids = []
        for scritto in linea:
            trovati = _candidati(scritto, rosa)
            if len(trovati) > 1:
                trovati = [v for v in trovati if v[0] not in sicuri] or trovati
            scelto = scelte.get(scritto)
            if scelto is not None and any(g == scelto for g, _, _ in trovati):
                trovati = [v for v in trovati if v[0] == scelto]
            if not trovati:
                lettura.mancanti.append(scritto)
            elif len(trovati) > 1:
                lettura.ambigui.append((scritto, [(g, n) for g, n, _ in trovati]))
            else:
                gid, nome, ruolo = trovati[0]
                ids.append(gid)
                lettura.nomi[gid] = nome
                ruoli[gid] = ruolo
        linee_id.append(ids)
    lettura.titolari = _griglie(linee_id, [len(l) for l in linee], ruoli)
    return lettura


def _griglie(
    linee_id: list[list[int]], lunghezze: list[int], ruoli: dict[int, str | None]
) -> list[tuple[int, str]]:
    """Griglia "riga:colonna": il portiere da solo in testa, poi le linee del testo sulle
    righe del campo; con un numero di linee strano, la riga del ruolo."""
    movimento = lunghezze[1:]
    if lunghezze and lunghezze[0] == 1 and len(movimento) in RIGHE_PER_LINEE:
        righe = (1,) + RIGHE_PER_LINEE[len(movimento)]
    else:
        righe = None
    risultato: list[tuple[int, str]] = []
    usati: dict[int, int] = {}
    for n, ids in enumerate(linee_id):
        for gid in ids:
            riga = righe[n] if righe else RIGA_DA_RUOLO.get(ruoli.get(gid) or "", 3)
            usati[riga] = usati.get(riga, 0) + 1
            risultato.append((gid, f"{riga}:{usati[riga]}"))
    return risultato


def salva(s: Session, partita: Partita, squadra_id: int, titolari: list[tuple[int, str]]) -> None:
    """Salva gli 11 titolari ufficiali di una squadra (sostituisce solo i suoi). La partita
    passa a "ufficiali" quando entrambe le squadre hanno i loro 11. ValueError se la
    formazione non e' completa o la squadra non gioca la partita."""
    if squadra_id not in (partita.casa_id, partita.trasferta_id):
        raise ValueError("La squadra non gioca questa partita")
    if len(titolari) != TITOLARI or len({g for g, _ in titolari}) != TITOLARI:
        raise ValueError("La formazione deve avere 11 giocatori diversi")
    s.execute(
        delete(Formazione).where(
            Formazione.partita_id == partita.id,
            Formazione.squadra_id == squadra_id,
            Formazione.tipo.in_(("ufficiale", "panchina")),
        )
    )
    for gid, griglia in titolari:
        s.add(Formazione(
            partita_id=partita.id, squadra_id=squadra_id, giocatore_id=gid,
            tipo="ufficiale", griglia=griglia,
        ))
    s.flush()
    per_squadra = dict(
        s.execute(
            select(Formazione.squadra_id, func.count())
            .where(Formazione.partita_id == partita.id, Formazione.tipo == "ufficiale")
            .group_by(Formazione.squadra_id)
        ).all()
    )
    if all(per_squadra.get(sq, 0) >= TITOLARI for sq in (partita.casa_id, partita.trasferta_id)):
        partita.stato_formazioni = "ufficiali"
    s.flush()
