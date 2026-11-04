"""Logica dell'app (caricamento dati, formattazione, scritture) senza dipendenze da Streamlit:
le pagine si limitano a mostrare quello che restituiscono queste funzioni."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.formazioni import riepilogo_cambi
from ammonizioni.config import COMPETIZIONI
from ammonizioni.db import repo
from ammonizioni.db.modelli import (
    DuelloManuale,
    Formazione,
    Giocatore,
    Partita,
    Presenza,
    Segnalazione,
    Squadra,
    UltimoAggiornamento,
)
from ammonizioni.motore.classifica import converti_quota
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.fattori.arbitro import fattore_arbitro
from ammonizioni.motore.mercati import MercatoAmmonizioni
from ammonizioni.motore.pesi import carica_pesi
from ammonizioni.motore.tipi import Candidato, DatiPartita, decimale

ROMA = ZoneInfo("Europe/Rome")
GIORNI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")
GIORNI_PROSSIME = 7
SOGLIA_PARTITA_CALDA = 1.1
FONTI_NON_TIPSTER = ("io", "modello")
COLONNE_TABELLA = (
    "Giocatore", "Squadra", "Probabilità", "Motivazioni", "Affidabilità",
    "Quota", "Implicita", "Valore", "Tipster",
)


# ---------------------------------------------------------------- formattazione

def data_italiana(dt_utc: datetime) -> str:
    """"sab 08/11 20:45" in Europe/Rome."""
    locale = dt_utc.astimezone(ROMA)
    return f"{GIORNI[locale.weekday()]} {locale:%d/%m %H:%M}"


def data_breve(dt_utc: datetime) -> str:
    """"08/11 20:45" in Europe/Rome."""
    return f"{dt_utc.astimezone(ROMA):%d/%m %H:%M}"


def percentuale(p: float) -> str:
    return f"{round(p * 100)}%"


def valore_testo(v: float) -> str:
    """Differenza in punti percentuali con segno: "+12%" / "-3%"."""
    return f"{round(v * 100):+d}%"


def link_sofascore(giocatore) -> str:
    """Pagina Sofascore del giocatore se nota, altrimenti una ricerca."""
    if giocatore.sofascore_url:
        return giocatore.sofascore_url
    return "https://www.google.com/search?q=sofascore+" + "+".join(giocatore.nome.split())


# ---------------------------------------------------------------- pagina Partite

@dataclass(frozen=True)
class RigaPartita:
    id: int
    quando: str
    giornata: int | None
    casa: str
    trasferta: str
    arbitro: str | None
    calda: bool
    formazioni: str


def stato_aggiornamento(s: Session) -> tuple[str, bool]:
    """(testo "Dati aggiornati: ...", ultimo job notturno completo?)."""
    quando = repo.ultimo_aggiornamento(s, "notte")
    if quando is None:
        return "Dati non ancora aggiornati", True
    riga = s.get(UltimoAggiornamento, "notte")
    return f"Dati aggiornati: {data_breve(quando)}", bool(riga.completo)


def e_partita_calda(dati: DatiPartita, pesi) -> bool:
    """Rivalità, campo caldo o arbitro con fattore >= 1.1 (per almeno una delle due squadre)."""
    if dati.contesto.rivalita or dati.contesto.campo_caldo:
        return True
    return any(
        fattore_arbitro(dati.arbitro, sq, dati.medie, pesi).valore >= SOGLIA_PARTITA_CALDA
        for sq in (dati.casa_id, dati.trasferta_id)
    )


def prossime_partite(s: Session, ora: datetime, giorni: int = GIORNI_PROSSIME) -> list[RigaPartita]:
    partite = s.execute(
        select(Partita)
        .where(
            Partita.competizione_id == COMPETIZIONI["serie_a"],
            Partita.data_utc >= ora,
            Partita.data_utc <= ora + timedelta(days=giorni),
        )
        .order_by(Partita.data_utc)
    ).scalars().all()
    if not partite:
        return []
    pesi = carica_pesi(s)
    nomi = {sq.id: sq.nome for sq in s.execute(select(Squadra)).scalars()}
    righe = []
    for p in partite:
        dati = carica_dati(s, p.id)
        righe.append(
            RigaPartita(
                id=p.id,
                quando=data_italiana(p.data_utc),
                giornata=p.giornata,
                casa=nomi.get(p.casa_id, str(p.casa_id)),
                trasferta=nomi.get(p.trasferta_id, str(p.trasferta_id)),
                arbitro=dati.arbitro.nome if dati.arbitro and dati.arbitro.nome else None,
                calda=e_partita_calda(dati, pesi),
                formazioni=p.stato_formazioni,
            )
        )
    return righe


# ---------------------------------------------------------------- pagina Dettaglio

@dataclass(frozen=True)
class InfoPartita:
    id: int
    data_utc: datetime
    giornata: int | None
    stato_formazioni: str


@dataclass(frozen=True)
class Dettaglio:
    partita: InfoPartita
    dati: DatiPartita
    candidati: list[Candidato]
    tipster: dict[int, list[str]]
    nomi_giocatori: dict[int, str]


def id_partita(valore) -> int | None:
    """Id dal parametro dell'URL; None se assente o non numerico."""
    try:
        return int(valore)
    except (TypeError, ValueError):
        return None


def carica_dettaglio(s: Session, partita_id: int, quote: dict[int, float]) -> Dettaglio | None:
    partita = s.get(Partita, partita_id)
    if partita is None:
        return None
    dati = carica_dati(s, partita_id)
    candidati = MercatoAmmonizioni().classifica(
        s, partita_id, quote=quote or None, titolari=dati.titolari
    )
    return Dettaglio(
        partita=InfoPartita(partita.id, partita.data_utc, partita.giornata, partita.stato_formazioni),
        dati=dati,
        candidati=candidati,
        tipster=tipster_per_giocatore(s, partita_id),
        nomi_giocatori={t.giocatore_id: t.nome for t in dati.titolari},
    )


def tipster_per_giocatore(s: Session, partita_id: int) -> dict[int, list[str]]:
    risultato: dict[int, list[str]] = {}
    righe = s.execute(
        select(Segnalazione.giocatore_id, Segnalazione.fonte)
        .where(Segnalazione.partita_id == partita_id, Segnalazione.fonte.not_in(FONTI_NON_TIPSTER))
        .order_by(Segnalazione.id)
    ).all()
    for giocatore_id, fonte in righe:
        if fonte not in risultato.setdefault(giocatore_id, []):
            risultato[giocatore_id].append(fonte)
    return risultato


def righe_contesto(dati: DatiPartita) -> list[str]:
    c = dati.contesto
    a = dati.arbitro
    if a is None or not a.nome:
        arbitro = "Arbitro: non ancora designato"
    else:
        arbitro = (
            f"Arbitro: {a.nome} · {decimale(a.gialli_medi)} gialli e "
            f"{decimale(a.falli_medi)} falli a partita ({a.partite} partite)"
        )
    posta = ", ".join(
        f"{dati.nomi_squadre.get(sq, sq)}: {p}"
        for sq, p in c.posta.items()
        if p
    ) or "nessuna in particolare"
    if c.precedenti_n and c.precedenti_gialli_medi is not None:
        precedenti = (
            f"Precedenti: {c.precedenti_n} partite, {decimale(c.precedenti_gialli_medi)} gialli di media"
        )
    else:
        precedenti = "Precedenti: nessuno nei dati"
    return [
        arbitro,
        f"Rivalità: {'sì' if c.rivalita else 'no'}" + (" · campo caldo" if c.campo_caldo else ""),
        f"Posta in palio: {posta}",
        precedenti,
    ]


def righe_cambi(s: Session, dettaglio: Dettaglio) -> list[str]:
    """Una riga per squadra con i cambi tra formazione probabile e ufficiale."""
    if dettaglio.partita.stato_formazioni != "ufficiali":
        return []
    cambi = riepilogo_cambi(s, dettaglio.partita.id)
    ids = {g for entrati, usciti in cambi.values() for g in entrati + usciti}
    nomi = {
        g.id: g.nome
        for g in s.execute(select(Giocatore).where(Giocatore.id.in_(ids))).scalars()
    } if ids else {}

    def elenco(lista: list[int]) -> str:
        return ", ".join(nomi.get(g, str(g)) for g in lista) or "nessuno"

    return [
        f"{dettaglio.dati.nomi_squadre.get(sq, sq)}: entrati {elenco(entrati)}; usciti {elenco(usciti)}"
        for sq, (entrati, usciti) in cambi.items()
    ]


def righe_tabella(
    candidati: list[Candidato], nomi_squadre: dict[int, str], tipster: dict[int, list[str]]
) -> list[dict[str, str]]:
    return [
        {
            "Giocatore": c.nome,
            "Squadra": nomi_squadre.get(c.squadra_id, ""),
            "Probabilità": percentuale(c.probabilita),
            "Motivazioni": " · ".join(c.motivazioni),
            "Affidabilità": c.affidabilita,
            "Quota": decimale(c.quota, 2) if c.quota else "",
            "Implicita": percentuale(c.prob_implicita) if c.prob_implicita else "",
            "Valore": valore_testo(c.valore) if c.valore is not None else "",
            "Tipster": ", ".join(tipster.get(c.giocatore_id, [])),
        }
        for c in candidati
    ]


def colore_valore(testo: str) -> str:
    """Stile CSS della cella Valore: verde se positivo."""
    return "background-color: #c8f0c8; color: #14532d" if testo.startswith("+") and testo != "+0%" else ""


def avversari_possibili(dati: DatiPartita, candidato: Candidato) -> list[tuple[int, str]]:
    return [
        (t.giocatore_id, t.nome) for t in dati.titolari if t.squadra_id != candidato.squadra_id
    ]


def statistiche_90(s: Session, giocatore_id: int, stagione: int, prima_di: datetime) -> dict[str, float]:
    """Medie per 90 minuti (gialli, falli, falli subiti, dribbling) nelle ultime 3 stagioni."""
    righe = s.execute(
        select(Presenza)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id == giocatore_id,
            Partita.data_utc < prima_di,
            Partita.stagione.in_((stagione, stagione - 1, stagione - 2)),
        )
    ).scalars().all()
    minuti = sum(r.minuti for r in righe)
    if minuti <= 0:
        return {"minuti": 0}

    def per90(valore: int) -> float:
        return valore / minuti * 90

    return {
        "minuti": minuti,
        "gialli90": per90(sum(r.gialli for r in righe)),
        "falli90": per90(sum(r.falli_commessi for r in righe)),
        "falli_subiti90": per90(sum(r.falli_subiti for r in righe)),
        "dribbling90": per90(sum(r.dribbling_tentati for r in righe)),
    }


def righe_duello(stat_a: dict[str, float], stat_b: dict[str, float]) -> list[dict[str, str]]:
    """Tabella affiancata delle statistiche per 90 minuti dei due giocatori."""
    etichette = (
        ("gialli90", "Gialli per 90'"),
        ("falli90", "Falli commessi per 90'"),
        ("falli_subiti90", "Falli subiti per 90'"),
        ("dribbling90", "Dribbling tentati per 90'"),
    )

    def cella(stat: dict[str, float], chiave: str) -> str:
        return decimale(stat[chiave], 2) if chiave in stat else "n.d."

    return [
        {"Statistica": nome, "Giocatore": cella(stat_a, k), "Avversario": cella(stat_b, k)}
        for k, nome in etichette
    ]


def storia_contro(
    s: Session, giocatore_id: int, squadra_avversaria_id: int, prima_di: datetime
) -> tuple[int, int]:
    """(partite giocate, gialli presi) dal giocatore contro la squadra avversaria."""
    righe = s.execute(
        select(Presenza)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id == giocatore_id,
            Presenza.minuti > 0,
            Presenza.squadra_id != squadra_avversaria_id,
            Partita.data_utc < prima_di,
            (Partita.casa_id == squadra_avversaria_id) | (Partita.trasferta_id == squadra_avversaria_id),
        )
    ).scalars().all()
    return len(righe), sum(r.gialli for r in righe)


def testo_storia(partite: int, gialli: int, squadra: str) -> str:
    if partite == 0:
        return f"Contro {squadra}: nessun precedente nei dati"
    return f"Contro {squadra}: {partite} partite, {gialli} gialli"


def giocatori_squadra(s: Session, squadra_id: int, inclusi: list[int]) -> list[tuple[int, str]]:
    """Giocatori noti della squadra (presenze, formazioni, più quelli in `inclusi`), per nome."""
    ids = set(inclusi)
    ids.update(
        s.execute(select(Presenza.giocatore_id).where(Presenza.squadra_id == squadra_id)).scalars()
    )
    ids.update(
        s.execute(select(Formazione.giocatore_id).where(Formazione.squadra_id == squadra_id)).scalars()
    )
    righe = s.execute(select(Giocatore.id, Giocatore.nome).where(Giocatore.id.in_(ids))).all()
    return sorted(((i, n) for i, n in righe), key=lambda r: r[1])


# ---------------------------------------------------------------- scritture

def salva_segnalazione(
    s: Session, partita_id: int, giocatore_id: int, tipster: str, quota_testo: str = ""
) -> None:
    """Segnalazione di un tipster; la quota è facoltativa. ValueError con messaggio italiano."""
    nome = tipster.strip()
    if not nome:
        raise ValueError("Inserisci il nome del tipster")
    quota = converti_quota(quota_testo) if quota_testo.strip() else None
    s.add(Segnalazione(partita_id=partita_id, giocatore_id=giocatore_id, fonte=nome, quota=quota))
    s.flush()


def salva_duello(s: Session, partita_id: int, giocatore_id: int, avversario_id: int) -> None:
    """Avversario diretto scelto a mano (sostituisce la scelta precedente per quel giocatore)."""
    precedenti = s.execute(
        select(DuelloManuale).where(
            DuelloManuale.partita_id == partita_id, DuelloManuale.giocatore_id == giocatore_id
        )
    ).scalars().all()
    for p in precedenti:
        s.delete(p)
    s.flush()
    s.add(DuelloManuale(partita_id=partita_id, giocatore_id=giocatore_id, avversario_id=avversario_id))
    s.flush()
