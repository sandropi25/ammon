"""Cache delle pagine: secondo caricamento senza DB, svuotata dopo le scritture."""
from datetime import datetime, timedelta, timezone

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import componenti
import pytest
from ayuda_app import PAGINA_DETTAGLIO, PAGINA_PARTITE, avvia, sessione_db, url_db, visibile
from db_prova import PARTITA_FUTURA, popola

from ammonizioni.db.modelli import Partita


@pytest.fixture(autouse=True)
def _cache_pulita():
    import streamlit as st

    st.cache_data.clear()
    yield
    st.cache_data.clear()


def _contatore(monkeypatch, nome):
    chiamate = []
    originale = getattr(componenti, nome)

    def contato(*args, **kwargs):
        chiamate.append(1)
        return originale(*args, **kwargs)

    monkeypatch.setattr(componenti, nome, contato)
    return chiamate


def test_dettaglio_secondo_caricamento_dalla_cache(sessione_db, monkeypatch):
    with sessione_db() as s:
        popola(s)
    chiamate = _contatore(monkeypatch, "carica_pagina_dettaglio")
    avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert len(chiamate) == 1


def test_scrittura_svuota_la_cache_del_dettaglio(sessione_db, monkeypatch):
    with sessione_db() as s:
        popola(s)
    chiamate = _contatore(monkeypatch, "carica_pagina_dettaglio")
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert len(chiamate) == 1
    at.text_input(key="tipster_nome").set_value("Luca")
    at.button(key="salva_tipster").click().run()
    assert not at.exception
    assert len(chiamate) == 2  # dopo il salvataggio la pagina e' stata riletta dal DB


def test_quota_non_ricarica_dal_db(sessione_db, monkeypatch):
    with sessione_db() as s:
        popola(s)
    chiamate = _contatore(monkeypatch, "carica_pagina_dettaglio")
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    at.text_input(key="quota_12").set_value("3,00")
    at.button(key="salva_quota_12").click().run()
    assert not at.exception
    assert len(chiamate) == 1  # le quote stanno in sessione: niente query


def test_partite_secondo_caricamento_dalla_cache(sessione_db, monkeypatch):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(days=2)
    chiamate = _contatore(monkeypatch, "prossime_partite")
    avvia(PAGINA_PARTITE)
    at = avvia(PAGINA_PARTITE)
    assert "Casa FC" in visibile(at)
    assert len(chiamate) == 1
