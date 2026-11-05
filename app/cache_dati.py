"""Cache di Streamlit sopra i caricamenti in sola lettura delle pagine.

Il database è remoto (ogni query costa decine di ms): i risultati si tengono 10 minuti e si
svuotano dopo ogni scrittura (`svuota`). La logica resta in componenti.py, senza Streamlit.
La chiave contiene solo argomenti semplici: l'URL del database (così database diversi, per
esempio nei test, non si mischiano), l'id della partita e l'ora arrotondata al minuto."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import componenti
from ammonizioni import config
from ammonizioni.db.sessione import apri

TTL_SECONDI = 600


@st.cache_data(ttl=TTL_SECONDI, show_spinner=False)
def _pagina_partite(db: str, minuto: datetime, campionati: tuple[int, ...]):
    with apri(db) as s:
        testo, completo = componenti.stato_aggiornamento(s)
        righe = componenti.prossime_partite(s, minuto, campionati=campionati)
    return testo, completo, righe


def pagina_partite(adesso: datetime, campionati: tuple[int, ...]):
    """(testo aggiornamento, ultimo job completo?, righe delle prossime partite)."""
    minuto = adesso.replace(second=0, microsecond=0)
    return _pagina_partite(config.url_database(), minuto, tuple(campionati))


@st.cache_data(ttl=TTL_SECONDI, show_spinner=False)
def _pagina_dettaglio(db: str, partita_id: int):
    with apri(db) as s:
        return componenti.carica_pagina_dettaglio(s, partita_id)


def pagina_dettaglio(partita_id: int):
    """PaginaDettaglio della partita (senza quote), o None se non esiste."""
    return _pagina_dettaglio(config.url_database(), partita_id)


def svuota() -> None:
    """Da chiamare dopo ogni scrittura che cambia quello che le pagine mostrano."""
    st.cache_data.clear()
