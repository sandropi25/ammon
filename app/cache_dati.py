"""Cache di Streamlit sopra i caricamenti in sola lettura delle pagine.

Il database è remoto (ogni query costa decine di ms): i risultati si tengono 10 minuti e si
svuotano dopo ogni scrittura (`svuota`). La logica resta in componenti.py, senza Streamlit.
La chiave contiene solo argomenti semplici: l'URL del database (così database diversi, per
esempio nei test, non si mischiano), l'id della partita e l'inizio dell'ora corrente."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import componenti
import componenti_arbitri
import componenti_calde
import componenti_calendario
import componenti_classifica
import componenti_cerca
import componenti_home
from ammonizioni import config
from ammonizioni.db.sessione import apri

TTL_SECONDI = 600


@st.cache_data(ttl=TTL_SECONDI, max_entries=20, show_spinner=False)
def _pagina_partite(db: str, blocco: datetime, campionati: tuple[int, ...]):
    # finestra larga: dall'inizio dell'ora a 7 giorni dopo la fine dell'ora; il filtro
    # esatto su "adesso" si fa fuori dalla cache
    with apri(db) as s:
        testo, completo = componenti.stato_aggiornamento(s)
        righe = componenti.prossime_partite(
            s, blocco, giorni=componenti.GIORNI_PROSSIME + 1, campionati=campionati
        )
    return testo, completo, righe


def pagina_partite(adesso: datetime, campionati: tuple[int, ...]):
    """(testo aggiornamento, ultimo job completo?, righe delle partite dei prossimi 7 giorni).
    La cache è per ora intera: dentro i 10 minuti non si tocca il DB neanche se passano i
    minuti; le partite già iniziate escono dall'elenco grazie al filtro finale."""
    blocco = adesso.replace(minute=0, second=0, microsecond=0)
    testo, completo, righe = _pagina_partite(config.url_database(), blocco, tuple(campionati))
    return testo, completo, componenti.nella_finestra(righe, adesso)


@st.cache_data(ttl=TTL_SECONDI, max_entries=10, show_spinner=False)
def _stato_aggiornamento(db: str):
    with apri(db) as s:
        return componenti.stato_aggiornamento(s)


def stato_aggiornamento() -> tuple[str, bool]:
    """("Dati aggiornati: ...", ultimo job completo?) per l'intestazione di ogni pagina."""
    return _stato_aggiornamento(config.url_database())


@st.cache_data(ttl=TTL_SECONDI, max_entries=50, show_spinner=False)
def _pagina_dettaglio(db: str, partita_id: int):
    with apri(db) as s:
        pagina = componenti.carica_pagina_dettaglio(s, partita_id)
    if pagina is None:
        # un'eccezione non viene messa in cache: una partita appena caricata si vede subito
        raise LookupError(partita_id)
    return pagina


def pagina_dettaglio(partita_id: int):
    """PaginaDettaglio della partita (senza quote), o None se non esiste."""
    try:
        return _pagina_dettaglio(config.url_database(), partita_id)
    except LookupError:
        return None


@st.cache_data(ttl=TTL_SECONDI, max_entries=2, show_spinner=False)
def _indice_ricerca(db: str):
    with apri(db) as s:
        return componenti_cerca.carica_indice(s)


def indice_ricerca():
    """Nomi di giocatori e squadre per la pagina Cerca (caricati una volta, poi in cache)."""
    return _indice_ricerca(config.url_database())


@st.cache_data(ttl=TTL_SECONDI, max_entries=50, show_spinner=False)
def _scheda_giocatore(db: str, giocatore_id: int, blocco: datetime):
    with apri(db) as s:
        scheda = componenti_cerca.scheda_giocatore(s, giocatore_id, blocco)
    if scheda is None:
        raise LookupError(giocatore_id)  # le eccezioni non finiscono in cache
    return scheda


def scheda_giocatore(giocatore_id: int, adesso: datetime):
    """SchedaGiocatore (cache per ora intera), o None se il giocatore non esiste."""
    blocco = adesso.replace(minute=0, second=0, microsecond=0)
    try:
        return _scheda_giocatore(config.url_database(), giocatore_id, blocco)
    except LookupError:
        return None


@st.cache_data(ttl=TTL_SECONDI, max_entries=50, show_spinner=False)
def _partite_squadra(db: str, squadra_id: int, blocco: datetime):
    with apri(db) as s:
        # un'ora in piu' all'inizio: il filtro esatto su "adesso" si fa fuori dalla cache
        return componenti_cerca.partite_squadra(
            s, squadra_id, blocco, giorni=componenti_cerca.GIORNI_SQUADRA + 1
        )


def partite_squadra(squadra_id: int, adesso: datetime):
    """Partite della squadra nei prossimi 30 giorni (cache per ora intera)."""
    blocco = adesso.replace(minute=0, second=0, microsecond=0)
    righe = _partite_squadra(config.url_database(), squadra_id, blocco)
    return componenti.nella_finestra(righe, adesso, giorni=componenti_cerca.GIORNI_SQUADRA)


@st.cache_data(ttl=TTL_SECONDI, max_entries=10, show_spinner=False)
def _calendario(db: str, campionato: int, stagione: int):
    with apri(db) as s:
        return componenti_calendario.carica_calendario(s, campionato, stagione)


def calendario(campionato: int, stagione: int = config.STAGIONE_CORRENTE):
    """Giornate (o settimane) del campionato nella stagione, con la giornata in corso: una
    sola query leggera, in cache."""
    return _calendario(config.url_database(), campionato, stagione)


@st.cache_data(ttl=TTL_SECONDI, max_entries=60, show_spinner=False)
def _righe_turno(db: str, ids: tuple[int, ...]):
    with apri(db) as s:
        return componenti_calendario.righe_turno(s, ids)


def righe_turno(turno) -> list:
    """Righe delle partite di un turno del calendario (poche query raggruppate, in cache)."""
    return _righe_turno(config.url_database(), tuple(turno.ids))


@st.cache_data(ttl=TTL_SECONDI, max_entries=10, show_spinner=False)
def _partite_calde(db: str, blocco: datetime, campionati: tuple[int, ...]):
    with apri(db) as s:
        return componenti_calde.partite_calde(s, blocco, campionati)


def partite_calde(adesso: datetime, campionati: tuple[int, ...]):
    """(partite calde dei prossimi 7 giorni, calde del resto della stagione), in cache per ora
    intera; le partite già iniziate escono col filtro finale, fuori dalla cache."""
    blocco = adesso.replace(minute=0, second=0, microsecond=0)
    righe = _partite_calde(config.url_database(), blocco, tuple(campionati))
    return componenti_calde.separa_prossimi_giorni(righe, adesso)


@st.cache_data(ttl=TTL_SECONDI, max_entries=5, show_spinner=False)
def _elenco_rivalita(db: str, blocco: datetime):
    with apri(db) as s:
        return componenti_calde.elenco_rivalita(s, blocco)


def elenco_rivalita(adesso: datetime):
    """Derby riconosciuti e campi caldi calcolati (sola lettura), in cache per ora intera."""
    return _elenco_rivalita(config.url_database(), adesso.replace(minute=0, second=0, microsecond=0))


@st.cache_data(ttl=TTL_SECONDI, max_entries=6, show_spinner=False)
def _statistiche_stagione(db: str, campionati: tuple[int, ...], stagione: int):
    with apri(db) as s:
        return componenti_home.statistiche_stagione(s, campionati, stagione)


def statistiche_stagione(campionati: tuple[int, ...], stagione: int = config.STAGIONE_CORRENTE):
    """Classifica degli ammoniti e dati dei grafici della Home (tre query raggruppate)."""
    return _statistiche_stagione(config.url_database(), tuple(campionati), stagione)


@st.cache_data(ttl=TTL_SECONDI, max_entries=6, show_spinner=False)
def _piu_a_rischio(db: str, partite: tuple[int, ...]):
    with apri(db) as s:
        return componenti_home.piu_a_rischio(s, list(partite))


def piu_a_rischio(partite: list[int]):
    """Giocatore più a rischio tra le partite date (modello del Dettaglio), in cache."""
    return _piu_a_rischio(config.url_database(), tuple(partite))


@st.cache_data(ttl=TTL_SECONDI, max_entries=6, show_spinner=False)
def _riepilogo_giocate(db: str, campionati: tuple[int, ...]):
    with apri(db) as s:
        return componenti_home.riepilogo_giocate(s, campionati)


def riepilogo_giocate(campionati: tuple[int, ...]):
    return _riepilogo_giocate(config.url_database(), tuple(campionati))


@st.cache_data(ttl=TTL_SECONDI, max_entries=6, show_spinner=False)
def _biografie(db: str, candidati: tuple[tuple[int, str], ...], oggi):
    with apri(db) as s:
        return componenti_home.biografie(s, candidati, oggi)


def biografie(righe, oggi):
    """Biografie (ESPN + Wikipedia) dei primi della classifica `righe` che ne hanno una."""
    return _biografie(config.url_database(), componenti_home.candidati_bio(righe), oggi)


@st.cache_data(ttl=TTL_SECONDI, max_entries=6, show_spinner=False)
def _classifiche(db: str, campionati: tuple[int, ...], stagione: int):
    with apri(db) as s:
        return componenti_classifica.carica_classifiche(s, campionati, stagione)


def classifiche(campionati: tuple[int, ...], stagione: int = config.STAGIONE_CORRENTE):
    """Classifiche dei campionati dati (tre query raggruppate in tutto), in cache."""
    return _classifiche(config.url_database(), tuple(campionati), stagione)


@st.cache_data(ttl=TTL_SECONDI, max_entries=6, show_spinner=False)
def _elenco_arbitri(db: str, campionati: tuple[int, ...]):
    with apri(db) as s:
        return componenti_arbitri.carica_elenco(s, campionati)


def elenco_arbitri(campionati: tuple[int, ...]):
    """Arbitri dei campionati dati con le loro medie (una query raggruppata), in cache."""
    return _elenco_arbitri(config.url_database(), tuple(campionati))


@st.cache_data(ttl=TTL_SECONDI, max_entries=50, show_spinner=False)
def _scheda_arbitro(db: str, arbitro_id: int, blocco: datetime):
    with apri(db) as s:
        scheda = componenti_arbitri.scheda_arbitro(s, arbitro_id, blocco)
    if scheda is None:
        raise LookupError(arbitro_id)  # le eccezioni non finiscono in cache
    return scheda


def scheda_arbitro(arbitro_id: int, adesso: datetime):
    """SchedaArbitro (cache per ora intera), o None se l'arbitro non esiste."""
    blocco = adesso.replace(minute=0, second=0, microsecond=0)
    try:
        return _scheda_arbitro(config.url_database(), arbitro_id, blocco)
    except LookupError:
        return None


def svuota() -> None:
    """Da chiamare dopo ogni scrittura che cambia quello che le pagine mostrano."""
    st.cache_data.clear()
