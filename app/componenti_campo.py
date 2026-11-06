"""Dati del campo con le formazioni del Dettaglio (senza Streamlit): posizioni dalla griglia
sintetica "riga:colonna", modulo, numeri di maglia, colori, panchine e rischio di giallo.

Solo dati semplici e congelati: finiscono nella cache di Streamlit insieme al Dettaglio."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra
from ammonizioni.motore.tipi import Candidato, Titolare

SOGLIA_GIALLO = 0.15  # sotto: bordo verde
SOGLIA_ROSSO = 0.30  # sopra: bordo rosso; in mezzo giallo
RIGA_DA_RUOLO = {"G": 1, "D": 2, "M": 3, "F": 5}
GIORNI_MAGLIA = 400  # numero di maglia dalle presenze dell'ultimo anno (o poco più)
PARTICELLE = {"de", "di", "da", "del", "della", "dos", "das", "van", "von", "le", "la", "dal", "mac"}


@dataclass(frozen=True)
class GiocatoreCampo:
    id: int
    nome: str
    cognome: str
    numero: int | None
    riga: int  # 1 portiere ... 5 attacco; 0 in panchina
    colonna: int  # 1 = la destra del giocatore
    in_riga: int  # quanti nella sua riga
    probabilita: float | None  # None: non candidato (portieri, panchinari non probabili)
    avversario_id: int | None
    volto: str | None  # foto ESPN (None: immagini spente)


@dataclass(frozen=True)
class SquadraCampo:
    id: int
    nome: str
    colore: str | None
    colore_alt: str | None
    logo: str | None
    modulo: str
    titolari: tuple[GiocatoreCampo, ...]
    panchina: tuple[GiocatoreCampo, ...]


@dataclass(frozen=True)
class DatiCampo:
    ufficiali: bool
    casa: SquadraCampo
    trasferta: SquadraCampo


def colore_valido(valore) -> str | None:
    """"#RRGGBB" (maiuscolo) o None: il colore finisce in un attributo dell'SVG."""
    if isinstance(valore, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", valore):
        return valore.upper()
    return None


def livello_rischio(probabilita: float | None) -> str:
    """"verde" (< 15%), "giallo" (15-30%), "rosso" (> 30%), "neutro" se non candidato."""
    if probabilita is None:
        return "neutro"
    if probabilita < SOGLIA_GIALLO:
        return "verde"
    if probabilita <= SOGLIA_ROSSO:
        return "giallo"
    return "rosso"


def cognome(nome: str) -> str:
    """Nome da scrivere sotto la maglietta: "Lautaro Martínez" -> "Martínez",
    "Matthijs de Ligt" -> "de Ligt", "Pedri" -> "Pedri"."""
    parole = nome.split()
    if len(parole) <= 1:
        return nome.strip()
    finale = [parole[-1]]
    for parola in reversed(parole[:-1]):
        if parola.lower() in PARTICELLE:
            finale.insert(0, parola)
        else:
            break
    return " ".join(finale)


def _riga_colonna(t: Titolare) -> tuple[int, int | None]:
    try:
        riga, colonna = (t.griglia or "").split(":")
        riga, colonna = int(riga), int(colonna)
    except ValueError:
        return RIGA_DA_RUOLO.get(t.ruolo, 3), None
    if not 1 <= riga <= 5:
        return RIGA_DA_RUOLO.get(t.ruolo, 3), None
    return riga, colonna


def posizioni(titolari: list[Titolare]) -> dict[int, tuple[int, int, int]]:
    """giocatore_id -> (riga, colonna, quanti nella riga). Dentro la riga l'ordine della
    griglia (da destra a sinistra, come nel motore), poi chi non ha griglia; le colonne si
    rinumerano da 1 così buchi o doppioni non sovrappongono i giocatori."""
    per_riga: dict[int, list[tuple[int, int]]] = {}
    for t in titolari:
        riga, colonna = _riga_colonna(t)
        per_riga.setdefault(riga, []).append((colonna if colonna is not None else 99, t.giocatore_id))
    risultato = {}
    for riga, elenco in per_riga.items():
        for n, (_, gid) in enumerate(sorted(elenco), start=1):
            risultato[gid] = (riga, n, len(elenco))
    return risultato


def modulo(pos: dict[int, tuple[int, int, int]]) -> str:
    """"4-3-3" dalle righe 2-5 (il portiere non conta); vuoto senza giocatori di movimento."""
    conteggio: dict[int, int] = {}
    for riga, _, _ in pos.values():
        if riga >= 2:
            conteggio[riga] = conteggio.get(riga, 0) + 1
    return "-".join(str(conteggio[r]) for r in sorted(conteggio))


def _maglie(
    s: Session, partita: Partita, ids: set[int], ufficiali: bool
) -> dict[int, int]:
    """Numeri di maglia: dalla formazione ufficiale (e panchina) della partita, altrimenti
    dall'ultima presenza dell'ultimo anno che lo ha. Due query per tutti."""
    if not ids:
        return {}
    maglie: dict[int, int] = {}
    if ufficiali:
        for gid, numero in s.execute(
            select(Formazione.giocatore_id, Formazione.maglia).where(
                Formazione.partita_id == partita.id,
                Formazione.tipo.in_(("ufficiale", "panchina")),
                Formazione.maglia.is_not(None),
            )
        ):
            maglie[int(gid)] = int(numero)
    mancanti = ids - set(maglie)
    if mancanti:
        righe = s.execute(
            select(Presenza.giocatore_id, Presenza.maglia)
            .join(Partita, Partita.id == Presenza.partita_id)
            .where(
                Presenza.giocatore_id.in_(mancanti),
                Presenza.maglia.is_not(None),
                Partita.data_utc < partita.data_utc,
                Partita.data_utc >= partita.data_utc - timedelta(days=GIORNI_MAGLIA),
            )
            .order_by(Partita.data_utc.desc())
        ).all()
        for gid, numero in righe:
            maglie.setdefault(int(gid), int(numero))  # la più recente vince
    return maglie


def _panchina_ufficiale(s: Session, partita_id: int) -> list[tuple[int, int, str]]:
    """(squadra_id, giocatore_id, nome) della panchina in distinta salvata con le ufficiali."""
    return [
        (int(sq), int(gid), nome)
        for sq, gid, nome in s.execute(
            select(Formazione.squadra_id, Formazione.giocatore_id, Giocatore.nome)
            .join(Giocatore, Giocatore.id == Formazione.giocatore_id)
            .where(Formazione.partita_id == partita_id, Formazione.tipo == "panchina")
            .order_by(Giocatore.nome)
        )
    ]


def carica_campo(
    s: Session,
    partita: Partita,
    titolari: list[Titolare],
    candidati: list[Candidato],
    subentranti: list[Candidato],
) -> DatiCampo:
    """Campo della partita: titolari dalla griglia salvata, panchina ufficiale (o, con le
    probabili, i probabili subentranti), maglie, colori e stemmi. Poche query raggruppate.
    Le probabilità sono quelle del modello: il campo non ne calcola di nuove."""
    ufficiali = partita.stato_formazioni == "ufficiali"
    immagini = componenti.immagini_attive(s)
    squadre = {
        q.id: q for q in s.scalars(
            select(Squadra).where(Squadra.id.in_((partita.casa_id, partita.trasferta_id)))
        )
    }
    prob = {c.giocatore_id: c.probabilita for c in [*candidati, *subentranti]}
    avversari = {c.giocatore_id: c.avversario_diretto_id for c in candidati}
    in_campo = {t.giocatore_id for t in titolari}
    if ufficiali:
        panchina = [r for r in _panchina_ufficiale(s, partita.id) if r[1] not in in_campo]
    else:
        panchina = [
            (c.squadra_id, c.giocatore_id, c.nome)
            for c in sorted(subentranti, key=lambda c: -c.probabilita)
            if c.giocatore_id not in in_campo
        ]
    maglie = _maglie(s, partita, in_campo | {gid for _, gid, _ in panchina}, ufficiali)

    def giocatore(gid: int, nome: str, riga: int, colonna: int, in_riga: int) -> GiocatoreCampo:
        return GiocatoreCampo(
            id=gid, nome=nome, cognome=cognome(nome), numero=maglie.get(gid),
            riga=riga, colonna=colonna, in_riga=in_riga, probabilita=prob.get(gid),
            avversario_id=avversari.get(gid),
            volto=componenti.url_volto(gid) if immagini else None,
        )

    def squadra(squadra_id: int) -> SquadraCampo:
        suoi = [t for t in titolari if t.squadra_id == squadra_id]
        pos = posizioni(suoi)
        q = squadre.get(squadra_id)
        return SquadraCampo(
            id=squadra_id,
            nome=q.nome if q else str(squadra_id),
            colore=colore_valido(q.colore) if q else None,
            colore_alt=colore_valido(q.colore_alt) if q else None,
            logo=componenti.url_https(q.logo_url) if (q and immagini) else None,
            modulo=modulo(pos),
            titolari=tuple(
                giocatore(t.giocatore_id, t.nome, *pos[t.giocatore_id])
                for t in sorted(suoi, key=lambda t: pos[t.giocatore_id])
            ),
            panchina=tuple(
                giocatore(gid, nome, 0, n, 0)
                for n, (sq, gid, nome) in enumerate((r for r in panchina if r[0] == squadra_id), 1)
            ),
        )

    return DatiCampo(
        ufficiali=ufficiali, casa=squadra(partita.casa_id), trasferta=squadra(partita.trasferta_id)
    )
