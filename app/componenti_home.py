"""Logica della pagina Home (senza Streamlit): riquadri della giornata, classifica degli
ammoniti della stagione, dati dei grafici e biografie dei giocatori.

Ogni cartellino conta: anche quelli presi dalla panchina (0 minuti) e dai subentrati di un
minuto. Le somme arrivano da query raggruppate; su Postgres SUM restituisce Decimal, quindi
ogni aggregato è convertito in int prima di usarlo."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

import componenti
import componenti_giocate
from ammonizioni.config import NOMI_CAMPIONATI, STAGIONE_CORRENTE
from ammonizioni.db.modelli import Giocata, Giocatore, Partita, Presenza, Squadra
from ammonizioni.motore import modello
from ammonizioni.motore.classifica import classifica
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.pesi import carica_pesi

MINUTI_DISPERSIONE = 270  # almeno 3 partite intere per il grafico falli/gialli
ECCESSO_FALLI = 1.2  # "in ritardo": falli per 90' almeno il 20% sopra la media...
DIFETTO_GIALLI = 0.6  # ...e gialli per fallo al massimo il 60% di quelli della media
PARTITE_RISCHIO = 10  # partite guardate per il giocatore più a rischio
PRIMI_GRAFICO = 15
BIO_MOSTRATE = 6


# ---------------------------------------------------------------- classifica

@dataclass(frozen=True)
class RigaClassifica:
    giocatore_id: int
    nome: str
    squadra: str
    ruolo: str
    presenze: int  # partite giocate (almeno un minuto)
    minuti: int
    gialli: int  # tutti, anche dalla panchina
    rossi: int
    falli: int

    @property
    def gialli_90(self) -> float | None:
        return self.gialli * 90 / self.minuti if self.minuti else None

    @property
    def falli_90(self) -> float | None:
        return self.falli * 90 / self.minuti if self.minuti else None


def _squadre_attuali(s: Session, ids: list[int], filtri: list) -> dict[int, int]:
    """Squadra dell'ultima presenza della stagione di ogni giocatore (una query)."""
    if not ids:
        return {}
    righe = s.execute(
        select(Presenza.giocatore_id, Presenza.squadra_id, func.max(Partita.data_utc))
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(*filtri)
        .group_by(Presenza.giocatore_id, Presenza.squadra_id)
    ).all()
    ultima: dict[int, tuple[datetime, int]] = {}
    for gid, sid, quando in righe:
        if gid not in ultima or quando > ultima[gid][0]:
            ultima[gid] = (quando, sid)
    return {gid: sid for gid, (_, sid) in ultima.items()}


def classifica_ammoniti(
    s: Session, campionati: tuple[int, ...], stagione: int = STAGIONE_CORRENTE
) -> list[RigaClassifica]:
    """Tutti i giocatori con almeno una presenza (anche solo in distinta) nella stagione dei
    campionati dati, dal più ammonito al meno (a parità: più rossi, più gialli per 90')."""
    filtri = [Partita.competizione_id.in_(campionati), Partita.stagione == stagione]
    righe = s.execute(
        select(
            Giocatore.id, Giocatore.nome, Giocatore.ruolo,
            func.sum(case((Presenza.minuti > 0, 1), else_=0)),
            func.sum(Presenza.minuti), func.sum(Presenza.gialli), func.sum(Presenza.rossi),
            func.sum(Presenza.falli_commessi),
        )
        .join(Presenza, Presenza.giocatore_id == Giocatore.id)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(*filtri)
        .group_by(Giocatore.id, Giocatore.nome, Giocatore.ruolo)
    ).all()
    squadra_di = _squadre_attuali(s, [r[0] for r in righe], filtri)
    nomi = {
        q.id: q.nome
        for q in s.execute(select(Squadra).where(Squadra.id.in_(set(squadra_di.values())))).scalars()
    } if squadra_di else {}
    voci = [
        RigaClassifica(
            giocatore_id=gid, nome=nome, squadra=nomi.get(squadra_di.get(gid), ""),
            ruolo=componenti.RUOLI_ESTESI.get(ruolo or "", ""),
            presenze=int(pres or 0), minuti=int(minuti or 0), gialli=int(gialli or 0),
            rossi=int(rossi or 0), falli=int(falli or 0),
        )
        for gid, nome, ruolo, pres, minuti, gialli, rossi, falli in righe
    ]
    return sorted(
        voci, key=lambda r: (-r.gialli, -r.rossi, -(r.gialli_90 or 0), r.nome, r.giocatore_id)
    )


ORDINAMENTI = {
    "Gialli": lambda r: (-r.gialli, -r.rossi, r.nome),
    "Rossi": lambda r: (-r.rossi, -r.gialli, r.nome),
    "Gialli per 90'": lambda r: (r.gialli_90 is None, -(r.gialli_90 or 0), r.nome),
    "Falli per 90'": lambda r: (r.falli_90 is None, -(r.falli_90 or 0), r.nome),
    "Presenze": lambda r: (-r.presenze, -r.gialli, r.nome),
}
COLONNE_CLASSIFICA = (
    "#", "Giocatore", "Squadra", "Ruolo", "Presenze", "Minuti", "Gialli", "Rossi",
    "Gialli 90'", "Falli 90'",
)


def filtra_e_ordina(
    righe: list[RigaClassifica], testo: str = "", ordine: str = "Gialli"
) -> list[RigaClassifica]:
    """Ricerca per nome o squadra (senza accenti né maiuscole) e ordinamento scelto."""
    from componenti_cerca import normalizza  # stesso confronto della pagina Cerca

    cercato = normalizza(testo or "")
    if cercato:
        righe = [r for r in righe if cercato in normalizza(f"{r.nome} {r.squadra}")]
    return sorted(righe, key=ORDINAMENTI.get(ordine, ORDINAMENTI["Gialli"]))


def _per90(valore: float | None) -> str:
    return "–" if valore is None else f"{valore:.2f}".replace(".", ",")


def righe_tabella(righe: list[RigaClassifica]) -> list[dict[str, object]]:
    """Righe per la tabella (numeri come numeri, per 90' come testo con la virgola)."""
    return [
        {
            "#": n, "Giocatore": r.nome, "Squadra": r.squadra, "Ruolo": r.ruolo,
            "Presenze": r.presenze, "Minuti": r.minuti, "Gialli": r.gialli, "Rossi": r.rossi,
            "Gialli 90'": round(r.gialli_90, 2) if r.gialli_90 is not None else None,
            "Falli 90'": round(r.falli_90, 2) if r.falli_90 is not None else None,
        }
        for n, r in enumerate(righe, start=1)
    ]


# ---------------------------------------------------------------- grafici

def in_ritardo(righe: list[RigaClassifica]) -> set[int]:
    """Giocatori che fanno molti falli ma prendono pochi gialli rispetto alla media (con
    almeno `MINUTI_DISPERSIONE` minuti): candidati a un giallo "in ritardo"."""
    adatti = [r for r in righe if r.minuti >= MINUTI_DISPERSIONE]
    minuti = sum(r.minuti for r in adatti)
    falli = sum(r.falli for r in adatti)
    if not minuti or not falli:
        return set()
    media_falli_90 = falli * 90 / minuti
    gialli_per_fallo = sum(r.gialli for r in adatti) / falli
    return {
        r.giocatore_id for r in adatti
        if r.falli
        and r.falli_90 >= media_falli_90 * ECCESSO_FALLI
        and r.gialli / r.falli <= gialli_per_fallo * DIFETTO_GIALLI
    }


def dati_dispersione(righe: list[RigaClassifica]) -> list[dict[str, object]]:
    ritardo = in_ritardo(righe)
    return [
        {
            # nomi dei campi senza apostrofo: Vega li legge come percorsi ("Falli 90'" rompe)
            "Giocatore": r.nome, "Squadra": r.squadra, "Falli90": round(r.falli_90, 2),
            "Gialli90": round(r.gialli_90, 2), "Gialli": r.gialli, "Minuti": r.minuti,
            "Gruppo": "In ritardo" if r.giocatore_id in ritardo else "Altri",
        }
        for r in righe if r.minuti >= MINUTI_DISPERSIONE
    ]


def dati_primi(righe: list[RigaClassifica], quanti: int = PRIMI_GRAFICO) -> list[dict[str, object]]:
    """I più ammoniti per il grafico a barre. L'etichetta è unica (gli omonimi hanno anche la
    squadra, o l'id): il grafico raggruppa per etichetta e sommerebbe due omonimi."""
    primi = [r for r in righe if r.gialli][:quanti]
    conta: dict[str, int] = {}
    for r in primi:
        conta[r.nome] = conta.get(r.nome, 0) + 1
    etichette: set[str] = set()
    voci = []
    for r in primi:
        etichetta = r.nome if conta[r.nome] == 1 else f"{r.nome} ({r.squadra})"
        if etichetta in etichette:
            etichetta = f"{etichetta} #{r.giocatore_id}"
        etichette.add(etichetta)
        voci.append({
            "Giocatore": etichetta, "Squadra": r.squadra, "Gialli": r.gialli, "Rossi": r.rossi,
        })
    return voci


def gialli_per_giornata(
    s: Session, campionati: tuple[int, ...], stagione: int = STAGIONE_CORRENTE
) -> list[dict[str, object]]:
    """Gialli totali (panchina compresa) e media a partita per giornata e campionato."""
    righe = s.execute(
        select(
            Partita.competizione_id, Partita.giornata, func.sum(Presenza.gialli),
            func.count(func.distinct(Partita.id)),
        )
        .join(Presenza, Presenza.partita_id == Partita.id)
        .where(
            Partita.competizione_id.in_(campionati), Partita.stagione == stagione,
            Partita.giornata.is_not(None),
        )
        .group_by(Partita.competizione_id, Partita.giornata)
    ).all()
    voci = [
        {
            "Campionato": NOMI_CAMPIONATI.get(c, str(c)), "Giornata": int(g),
            "Gialli": int(tot or 0),
            "Media a partita": round(int(tot or 0) / int(n), 2) if n else 0.0,
        }
        for c, g, tot, n in righe
    ]
    return sorted(voci, key=lambda v: (v["Campionato"], v["Giornata"]))


def media_gialli_squadre(
    s: Session, campionati: tuple[int, ...], stagione: int = STAGIONE_CORRENTE
) -> list[dict[str, object]]:
    """Gialli a partita di ogni squadra nella stagione (panchina compresa), dalla più alta."""
    righe = s.execute(
        select(
            Presenza.squadra_id, func.sum(Presenza.gialli),
            func.count(func.distinct(Presenza.partita_id)),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(Partita.competizione_id.in_(campionati), Partita.stagione == stagione)
        .group_by(Presenza.squadra_id)
    ).all()
    nomi = {
        q.id: q.nome
        for q in s.execute(select(Squadra).where(Squadra.id.in_([r[0] for r in righe]))).scalars()
    } if righe else {}
    voci = [
        {
            "Squadra": nomi.get(sid, str(sid)), "Gialli": int(tot or 0), "Partite": int(n),
            "Media": round(int(tot or 0) / int(n), 2),
        }
        for sid, tot, n in righe if n
    ]
    return sorted(voci, key=lambda v: (-v["Media"], v["Squadra"]))


@dataclass(frozen=True)
class StatisticheStagione:
    classifica: list[RigaClassifica]
    per_giornata: list[dict[str, object]]
    per_squadra: list[dict[str, object]]


def statistiche_stagione(
    s: Session, campionati: tuple[int, ...], stagione: int = STAGIONE_CORRENTE
) -> StatisticheStagione:
    return StatisticheStagione(
        classifica=classifica_ammoniti(s, campionati, stagione),
        per_giornata=gialli_per_giornata(s, campionati, stagione),
        per_squadra=media_gialli_squadre(s, campionati, stagione),
    )


# ---------------------------------------------------------------- riquadri

def oggi_e_domani(righe: list[componenti.RigaPartita], adesso: datetime) -> list[componenti.RigaPartita]:
    """Le partite (già filtrate da adesso in poi) di oggi e di domani, ora di Roma."""
    oggi = adesso.astimezone(componenti.ROMA).date()
    giorni = (oggi, oggi + timedelta(days=1))
    return sorted(
        (r for r in righe if r.data_utc is not None
         and r.data_utc.astimezone(componenti.ROMA).date() in giorni),
        key=lambda r: (r.data_utc, r.id),
    )


def piu_calda(righe: list[componenti.RigaPartita]) -> componenti.RigaPartita | None:
    """La partita calda con più cartellini attesi (a parità la più vicina)."""
    if not righe:
        return None
    return max(righe, key=lambda r: (r.attesi or 0.0, -r.data_utc.timestamp(), -r.id))


@dataclass(frozen=True)
class PiuARischio:
    giocatore_id: int
    nome: str
    squadra: str
    probabilita: float
    partita_id: int
    partita: str  # "Inter – Milan"


def piu_a_rischio(s: Session, partite_ids: list[int]) -> PiuARischio | None:
    """Il candidato con la probabilità di ammonizione più alta tra le partite date (le
    prime `PARTITE_RISCHIO`), con lo stesso modello della pagina Dettaglio."""
    pesi = carica_pesi(s)
    scelto = modello.modello_scelto(s)
    coeff = modello.carica_coefficienti(s) if scelto == modello.V2 else None
    migliore: PiuARischio | None = None
    for pid in partite_ids[:PARTITE_RISCHIO]:
        try:
            # V2 divide i cartellini attesi su tutta la distinta: serve anche la panchina
            dati = carica_dati(s, pid, con_panchina=scelto == modello.V2)
        except (LookupError, ValueError):
            continue
        if scelto == modello.V2:
            candidati = modello.applica_v2(dati, pesi, coeff, classifica(dati, pesi, None), [])[0]
        else:
            candidati = classifica(dati, pesi, None)
        if not candidati:
            continue
        c = max(candidati, key=lambda c: (c.probabilita, -c.giocatore_id))
        if migliore is None or c.probabilita > migliore.probabilita:
            nomi = dati.nomi_squadre
            migliore = PiuARischio(
                giocatore_id=c.giocatore_id, nome=c.nome, squadra=nomi.get(c.squadra_id, ""),
                probabilita=c.probabilita, partita_id=pid,
                partita=f"{nomi.get(dati.casa_id, '')} – {nomi.get(dati.trasferta_id, '')}",
            )
    return migliore


@dataclass(frozen=True)
class RiepilogoGiocate:
    ultime: list[dict[str, str]]  # le ultime 3 del registro
    chiuse: int  # vinte + perse
    vinte: int
    profitto: float
    rendimento: float | None  # profitto / puntate chiuse


def riepilogo_giocate(s: Session, campionati: tuple[int, ...]) -> RiepilogoGiocate:
    ids = componenti_giocate.partite_con_giocate(s, campionati)
    ultime = componenti_giocate.righe_registro(s, campionati)[:3]
    giocate = s.execute(
        select(Giocata.esito, Giocata.quota, Giocata.puntata)
        .where(Giocata.partita_id.in_(ids or {-1}), Giocata.esito.in_(("vinta", "persa")))
    ).all()
    puntate = sum(float(p) for _, _, p in giocate)
    profitto = sum(
        float(p) * (float(q) - 1) if esito == "vinta" else -float(p) for esito, q, p in giocate
    )
    return RiepilogoGiocate(
        ultime=ultime, chiuse=len(giocate), vinte=sum(1 for e, _, _ in giocate if e == "vinta"),
        profitto=profitto, rendimento=profitto / puntate if puntate else None,
    )


# ---------------------------------------------------------------- biografie

@dataclass(frozen=True)
class Biografia:
    giocatore_id: int
    nome: str
    squadra: str
    eta: int | None
    nazionalita: str | None
    altezza_cm: int | None
    posizione: str | None
    estratto: str | None
    wiki_url: str | None


def eta(nascita: date | None, oggi: date) -> int | None:
    if nascita is None:
        return None
    return oggi.year - nascita.year - ((oggi.month, oggi.day) < (nascita.month, nascita.day))


CANDIDATI_BIO = 60  # primi della classifica tra cui cercare chi ha una biografia


def candidati_bio(righe: list[RigaClassifica]) -> tuple[tuple[int, str], ...]:
    """(id, squadra) dei primi della classifica: la chiave (piccola) della cache delle bio."""
    return tuple((r.giocatore_id, r.squadra) for r in righe[:CANDIDATI_BIO])


def biografie(
    s: Session, candidati: tuple[tuple[int, str], ...], oggi: date, quanti: int = BIO_MOSTRATE
) -> list[Biografia]:
    """Biografie dei primi `candidati` (id, squadra) che ne hanno una, nell'ordine dato
    (una query)."""
    ordine = [gid for gid, _ in candidati]
    if not ordine:
        return []
    squadre = dict(candidati)
    giocatori = {
        g.id: g for g in s.execute(select(Giocatore).where(Giocatore.id.in_(ordine))).scalars()
    }
    voci = []
    for gid in ordine:
        g = giocatori.get(gid)
        if g is None or not (g.wiki_estratto or g.data_nascita or g.nazionalita):
            continue
        voci.append(Biografia(
            giocatore_id=g.id, nome=g.nome, squadra=squadre.get(gid, ""),
            eta=eta(g.data_nascita, oggi), nazionalita=g.nazionalita, altezza_cm=g.altezza_cm,
            posizione=g.posizione, estratto=g.wiki_estratto,
            wiki_url=g.wiki_url if g.wiki_estratto else None,
        ))
        if len(voci) >= quanti:
            break
    return voci
