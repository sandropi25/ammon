"""Cache di Streamlit sopra i caricamenti in sola lettura delle pagine.

Il database è remoto (ogni query costa decine di ms): i risultati si tengono 10 minuti e si
svuotano dopo ogni scrittura (`svuota`). La logica resta in componenti.py, senza Streamlit.
La chiave contiene solo argomenti semplici: l'URL del database (così database diversi, per
esempio nei test, non si mischiano), l'id della partita e l'inizio dell'ora corrente."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import componenti
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


def svuota() -> None:
    """Da chiamare dopo ogni scrittura che cambia quello che le pagine mostrano."""
    st.cache_data.clear()
