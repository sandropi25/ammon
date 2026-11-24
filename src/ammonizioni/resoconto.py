"""Cernita salvata prima della partita e resoconto automatico a fine giornata.

- `salva_cernita`: il job pre-partita fissa la classifica V2 (titolari + panchina) prima del
  calcio d'inizio, con le probabili e poi di nuovo con le ufficiali. Impostazione
  "cernita_<partita>": {"ids": [...], "formazioni": "probabili"|"ufficiali", "salvata_utc"}.
- `chiudi_giornate`: quando l'ultima partita di una giornata di campionato e' chiusa (tutte e
  quattro le leghe), l'orchestratore scrive il resoconto: risultato, arbitro, ammoniti col minuto
  e la posizione in cernita, chi ha fatto tanti falli senza giallo. Impostazione
  "resoconto_<campionato>_<stagione>_<giornata>"; la precisione cumulata della cernita per lega
  in "precisione_cernita". Nessuna richiesta esterna: legge solo il database.
- Marcatori (beta): cernita in "marcatori_cernita_<partita>", stessi tempi; il resoconto riporta
  chi ha segnato con la posizione in cernita e quante volte almeno uno dei primi 3 ha segnato.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI, STATI_FINITI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Arbitro, Giocatore, Partita, Presenza, Squadra

log = logging.getLogger(__name__)

STATI_ESCLUSI = ("PST", "CANC")
CHIAVE_PRECISIONE = "precisione_cernita"
PRIMI = 3  # "almeno uno dei primi 3 della cernita ammonito"
FALLI_GRAZIATO = 3  # falli commessi senza giallo per finire tra i graziati
GIORNI_RESOCONTO = 10  # giornate finite da piu' tempo restano fuori (niente arretrati)
VICINANZA_GIORNATA = timedelta(days=3)  # giornata mancante: quella della partita piu' vicina


def chiave_cernita(partita_id: int) -> str:
    return f"cernita_{partita_id}"


def chiave_cernita_marcatori(partita_id: int) -> str:
    return f"marcatori_cernita_{partita_id}"


def chiave_resoconto(competizione_id: int, stagione: int, giornata: int) -> str:
    return f"resoconto_{competizione_id}_{stagione}_{giornata}"


def _utc(quando: datetime) -> datetime:
    return quando.replace(tzinfo=timezone.utc) if quando.tzinfo is None else quando


def classifica_v2(s: Session, partita_id: int) -> list[int]:
    """Id dei giocatori (titolari e panchina) dal piu' al meno probabile ammonito, modello V2."""
    from ammonizioni.motore import modello
    from ammonizioni.motore.dati import carica_dati
    from ammonizioni.motore.pesi import carica_pesi

    dati = carica_dati(s, partita_id, con_panchina=True)
    titolari, panchina = modello.candidati(
        dati, carica_pesi(s), None, modello.V2, modello.carica_coefficienti(s)
    )
    return [c.giocatore_id for c in sorted(titolari + panchina, key=lambda c: -c.probabilita)]


def salva_cernita(s: Session, partita: Partita, adesso_utc: datetime, classifica=None) -> bool:
    """Fissa la cernita prima del via: se non c'e' ancora, o se ora le formazioni sono ufficiali
    e quella salvata era sulle probabili. Dopo il calcio d'inizio non cambia piu'."""
    if adesso_utc >= _utc(partita.data_utc):
        return False
    chiave = chiave_cernita(partita.id)
    salvata = repo.leggi_impostazione(s, chiave, None)
    if salvata and (
        salvata.get("formazioni") == "ufficiali" or partita.stato_formazioni != "ufficiali"
    ):
        return False
    ids = (classifica or classifica_v2)(s, partita.id)
    if not ids:
        return False
    repo.scrivi_impostazione(
        s, chiave,
        {"ids": ids, "formazioni": partita.stato_formazioni, "salvata_utc": adesso_utc.isoformat()},
    )
    return True


def classifica_marcatori(s: Session, partita: Partita, cache: dict) -> list[tuple[int, float]]:
    """(giocatore, probabilita') dal modello marcatori; lo storico si costruisce una volta per
    giro (`cache`), perche' costa qualche secondo."""
    from ammonizioni.marcatori.pronostici import pronostica, storico_fino_a

    if "storico" not in cache:
        cache["storico"] = storico_fino_a(s, _utc(partita.data_utc))
    pronostico = pronostica(s, [partita], cache["storico"])[0]
    return [(x.giocatore_id, round(x.probabilita, 4)) for x in pronostico.previsioni]


def salva_cernita_marcatori(
    s: Session, partita: Partita, adesso_utc: datetime, cache: dict, classifica=None
) -> bool:
    """Come `salva_cernita`, per i marcatori (solo campionati): fissata prima del via, rifatta
    una volta con le ufficiali."""
    if partita.competizione_id not in CAMPIONATI or adesso_utc >= _utc(partita.data_utc):
        return False
    chiave = chiave_cernita_marcatori(partita.id)
    salvata = repo.leggi_impostazione(s, chiave, None)
    if salvata and (
        salvata.get("formazioni") == "ufficiali" or partita.stato_formazioni != "ufficiali"
    ):
        return False
    lista = (classifica or classifica_marcatori)(s, partita, cache)
    if not lista:
        return False
    repo.scrivi_impostazione(s, chiave, {
        "ids": [g for g, _ in lista], "probabilita": [q for _, q in lista],
        "formazioni": partita.stato_formazioni, "salvata_utc": adesso_utc.isoformat(),
    })
    return True


def resoconto_partita(s: Session, partita: Partita) -> dict:
    nomi = {
        q.id: q.nome
        for q in s.scalars(select(Squadra).where(Squadra.id.in_((partita.casa_id, partita.trasferta_id))))
    }
    arbitro = s.get(Arbitro, partita.arbitro_id) if partita.arbitro_id else None
    cernita = repo.leggi_impostazione(s, chiave_cernita(partita.id), None) or {}
    posizione = {gid: i for i, gid in enumerate(cernita.get("ids", []), 1)}
    righe = s.execute(
        select(Presenza, Giocatore.nome)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(Presenza.partita_id == partita.id)
    ).all()
    ammoniti = sorted(
        (
            {
                "giocatore_id": p.giocatore_id, "nome": nome, "squadra": nomi.get(p.squadra_id),
                "minuto": p.minuto_giallo, "rosso": bool(p.rossi), "titolare": bool(p.titolare),
                "falli": p.falli_commessi, "posizione": posizione.get(p.giocatore_id),
            }
            for p, nome in righe
            if p.gialli or p.rossi
        ),
        key=lambda a: (a["minuto"] is None, a["minuto"] or 0),
    )
    graziati = sorted(
        (
            {"giocatore_id": p.giocatore_id, "nome": nome, "squadra": nomi.get(p.squadra_id),
             "falli": p.falli_commessi}
            for p, nome in righe
            if not (p.gialli or p.rossi) and p.falli_commessi >= FALLI_GRAZIATO
        ),
        key=lambda g: -g["falli"],
    )
    primi = set(cernita.get("ids", [])[:PRIMI])
    cernita_m = repo.leggi_impostazione(s, chiave_cernita_marcatori(partita.id), None) or {}
    posizione_m = {gid: i for i, gid in enumerate(cernita_m.get("ids", []), 1)}
    primi_m = set(cernita_m.get("ids", [])[:PRIMI])
    marcatori = sorted(
        (
            {"giocatore_id": p.giocatore_id, "nome": nome, "squadra": nomi.get(p.squadra_id),
             "gol": p.gol, "posizione": posizione_m.get(p.giocatore_id)}
            for p, nome in righe
            if p.gol
        ),
        key=lambda m: -m["gol"],
    )
    return {
        "partita_id": partita.id,
        "casa": nomi.get(partita.casa_id), "trasferta": nomi.get(partita.trasferta_id),
        "gol_casa": partita.gol_casa, "gol_trasferta": partita.gol_trasferta,
        "arbitro": arbitro.nome_visualizzato if arbitro else None,
        "gialli": partita.gialli_totali, "rossi": partita.rossi_totali,
        "falli": partita.falli_totali,
        "cernita": cernita.get("formazioni"),
        "primi_ammoniti": sum(1 for a in ammoniti if a["giocatore_id"] in primi) if primi else None,
        "ammoniti": ammoniti,
        "graziati": graziati,
        "marcatori": marcatori,
        "cernita_marcatori": cernita_m.get("formazioni"),
        "primi_marcatori": (
            sum(1 for m in marcatori if m["giocatore_id"] in primi_m) if primi_m else None
        ),
    }


def _con_giornata(partite: list[Partita]) -> list[tuple[Partita, int]]:
    """Ogni partita con la sua giornata; se manca (spesso in Ligue 1) prende quella della
    partita piu' vicina nel tempo dello stesso campionato e stagione, entro 3 giorni."""
    note = [p for p in partite if p.giornata is not None]
    risultato = []
    for p in partite:
        if p.giornata is not None:
            risultato.append((p, p.giornata))
            continue
        vicine = [
            q for q in note
            if q.competizione_id == p.competizione_id and q.stagione == p.stagione
            and abs(_utc(q.data_utc) - _utc(p.data_utc)) <= VICINANZA_GIORNATA
        ]
        if vicine:
            vicina = min(vicine, key=lambda q: abs(_utc(q.data_utc) - _utc(p.data_utc)))
            risultato.append((p, vicina.giornata))
    return risultato


def giornate_concluse(s: Session, adesso_utc: datetime, chiuse: set[int]) -> list[tuple[int, int, int, list[Partita]]]:
    """Giornate di campionato con tutte le partite chiuse (statistiche scaricate o chiusura
    data per persa), l'ultima negli ultimi 10 giorni, senza resoconto."""
    partite = list(
        s.scalars(
            select(Partita)
            .where(
                Partita.competizione_id.in_(CAMPIONATI),
                Partita.data_utc >= adesso_utc - timedelta(days=GIORNI_RESOCONTO + 14),
                Partita.data_utc <= adesso_utc + timedelta(days=14),
            )
            .order_by(Partita.data_utc, Partita.id)
        )
    )
    gruppi: dict[tuple[int, int, int], list[Partita]] = {}
    for p, giornata in _con_giornata(partite):
        gruppi.setdefault((p.competizione_id, p.stagione, giornata), []).append(p)
    pronte = []
    for (comp, stagione, giornata), gruppo in gruppi.items():
        giocate = [p for p in gruppo if p.stato not in STATI_ESCLUSI]
        if not giocate:
            continue
        if not all(
            p.stato in STATI_FINITI and (p.statistiche_scaricate or p.id in chiuse) for p in giocate
        ):
            continue
        if _utc(giocate[-1].data_utc) < adesso_utc - timedelta(days=GIORNI_RESOCONTO):
            continue
        if repo.leggi_impostazione(s, chiave_resoconto(comp, stagione, giornata), None) is not None:
            continue
        pronte.append((comp, stagione, giornata, giocate))
    pronte.sort(key=lambda g: (CAMPIONATI.index(g[0]), g[1], g[2]))
    return pronte


def chiudi_giornate(s: Session, adesso_utc: datetime, chiuse: set[int]) -> int:
    """Scrive il resoconto delle giornate appena concluse e aggiorna la precisione cumulata
    della cernita per lega. Restituisce quante giornate ha chiuso."""
    precisione = dict(repo.leggi_impostazione(s, CHIAVE_PRECISIONE, {}) or {})
    fatte = 0
    for comp, stagione, giornata, partite in giornate_concluse(s, adesso_utc, chiuse):
        resoconti = [resoconto_partita(s, p) for p in partite]
        con_cernita = [r for r in resoconti if r["primi_ammoniti"] is not None]
        azzeccate = sum(1 for r in con_cernita if r["primi_ammoniti"] > 0)
        gialli = sum(r["gialli"] or 0 for r in resoconti)
        con_marcatori = [r for r in resoconti if r["primi_marcatori"] is not None]
        azzeccate_m = sum(1 for r in con_marcatori if r["primi_marcatori"] > 0)
        repo.scrivi_impostazione(
            s, chiave_resoconto(comp, stagione, giornata),
            {
                "competizione_id": comp, "stagione": stagione, "giornata": giornata,
                "creato_utc": adesso_utc.isoformat(),
                "partite": resoconti,
                "gialli_medi": round(gialli / len(resoconti), 2),
                "partite_con_cernita": len(con_cernita),
                "partite_primi_ammoniti": azzeccate,
                "partite_con_cernita_marcatori": len(con_marcatori),
                "partite_primi_marcatori": azzeccate_m,
            },
        )
        voce = dict(precisione.get(str(comp), {}))
        voce["giornate"] = voce.get("giornate", 0) + 1
        voce["partite"] = voce.get("partite", 0) + len(resoconti)
        voce["gialli"] = voce.get("gialli", 0) + gialli
        voce["partite_con_cernita"] = voce.get("partite_con_cernita", 0) + len(con_cernita)
        voce["partite_primi_ammoniti"] = voce.get("partite_primi_ammoniti", 0) + azzeccate
        voce["partite_con_cernita_marcatori"] = voce.get("partite_con_cernita_marcatori", 0) + len(con_marcatori)
        voce["partite_primi_marcatori"] = voce.get("partite_primi_marcatori", 0) + azzeccate_m
        voce["ultima"] = f"{stagione}/{giornata}"
        precisione[str(comp)] = voce
        log.info(
            "Resoconto %s giornata %s: %s partite, %.2f gialli a partita, primi %s ammoniti in %s "
            "partite su %s con cernita",
            NOMI_CAMPIONATI.get(comp, comp), giornata, len(resoconti), gialli / len(resoconti),
            PRIMI, azzeccate, len(con_cernita),
        )
        fatte += 1
    if fatte:
        repo.scrivi_impostazione(s, CHIAVE_PRECISIONE, precisione)
    return fatte
