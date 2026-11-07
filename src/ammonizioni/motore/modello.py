"""Scelta del modello (impostazione "Modello: V1 / V2") e candidati della partita.

V1 è il modello a fattori moltiplicativi (`classifica`). V2 (`motore.v2`) usa gli stessi
candidati, motivazioni e affidabilità di V1 ma cambia la probabilità: cartellini attesi della
partita divisi fra i giocatori. V1 resta il predefinito finché la prova non giustifica V2."""
from __future__ import annotations

import logging
from dataclasses import replace

from sqlalchemy.orm import Session

from ammonizioni.db.repo import leggi_impostazione, scrivi_impostazione
from ammonizioni.motore import v2
from ammonizioni.motore.classifica import classifica, classifica_subentranti
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import Candidato, DatiPartita, Fattore

log = logging.getLogger(__name__)

CHIAVE_MODELLO = "modello"
CHIAVE_COEFFICIENTI = "modello_v2_coefficienti"
V1, V2 = "V1", "V2"
MODELLI = (V1, V2)
PREDEFINITO = V1


def modello_scelto(s: Session) -> str:
    valore = leggi_impostazione(s, CHIAVE_MODELLO, PREDEFINITO)
    return valore if valore in MODELLI else PREDEFINITO


def salva_modello(s: Session, modello: str) -> None:
    if modello not in MODELLI:
        raise ValueError(f"Modello sconosciuto: {modello}")
    scrivi_impostazione(s, CHIAVE_MODELLO, modello)


def carica_coefficienti(s: Session) -> v2.CoefficientiV2:
    """Coefficienti stimati salvati; senza (o non validi) quelli predefiniti del modulo."""
    salvati = v2.CoefficientiV2.da_json(leggi_impostazione(s, CHIAVE_COEFFICIENTI, None))
    if salvati is None:
        return v2.COEFFICIENTI_PREDEFINITI
    return salvati


def salva_coefficienti(s: Session, coeff: v2.CoefficientiV2) -> None:
    scrivi_impostazione(s, CHIAVE_COEFFICIENTI, coeff.come_json())


SPIEGAZIONE = {
    V1: "V1: probabilità di base del giocatore moltiplicata per i fattori (arbitro, duello, "
        "contesto, storia, situazione).",
    V2: "V2: gialli attesi della partita (arbitro, squadre, derby, classifica) divisi fra i "
        "giocatori della distinta secondo la propensione di ciascuno; la somma delle "
        "probabilità torna con i gialli attesi.",
}


def descrizione_coefficienti(coeff: v2.CoefficientiV2) -> str:
    """Da dove vengono i coefficienti di V2, in chiaro."""
    campione = coeff.campione or {}
    nomi = {135: "Serie A", 140: "Liga"}
    campionati = ", ".join(nomi.get(c, str(c)) for c in campione.get("campionati", []))
    stagioni = ", ".join(str(x) for x in campione.get("stagioni", []))
    quando = coeff.stimati_il or "data sconosciuta"
    if quando[:4].isdigit() and len(quando) == 10:
        quando = f"{quando[8:10]}/{quando[5:7]}/{quando[:4]}"
    dettagli = " · ".join(t for t in (campionati, stagioni) if t)
    partite = campione.get("partite")
    testo = f"Coefficienti V2 stimati il {quando}"
    if partite:
        testo += f" su {partite} partite"
    if dettagli:
        testo += f" ({dettagli})"
    return testo


def _con_probabilita(c: Candidato, p: float, lam: float, quota: float) -> Candidato:
    valore = p - c.prob_implicita if c.prob_implicita is not None else None
    fattori = [*c.fattori, Fattore("partita", lam, None, 0), Fattore("quota", quota, None, 0)]
    return replace(c, probabilita=p, valore=valore, fattori=fattori)


def applica_v2(
    dati: DatiPartita,
    pesi: Pesi,
    coeff: v2.CoefficientiV2,
    titolari: list[Candidato],
    panchina: list[Candidato],
) -> tuple[list[Candidato], list[Candidato]]:
    """I candidati di V1 con la probabilità di V2, riordinati."""
    prev = v2.previsione(dati, pesi, coeff)

    def rifai(lista: list[Candidato]) -> list[Candidato]:
        nuovi = [
            _con_probabilita(
                c, prev.probabilita.get(c.giocatore_id, 0.0), prev.lambda_partita,
                prev.quote.get(c.giocatore_id, 0.0),
            )
            for c in lista
        ]
        nuovi.sort(key=lambda c: (-c.probabilita, c.giocatore_id))
        return nuovi

    return rifai(titolari), rifai(panchina)


def candidati(
    dati: DatiPartita,
    pesi: Pesi,
    quote: dict[int, float] | None = None,
    modello: str = PREDEFINITO,
    coeff: v2.CoefficientiV2 | None = None,
) -> tuple[list[Candidato], list[Candidato]]:
    """(titolari, probabili subentranti) col modello scelto."""
    titolari = classifica(dati, pesi, quote)
    panchina = classifica_subentranti(dati, pesi, quote)
    if modello != V2:
        return titolari, panchina
    return applica_v2(dati, pesi, coeff or v2.COEFFICIENTI_PREDEFINITI, titolari, panchina)
