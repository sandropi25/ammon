"""Cache delle pagine: secondo caricamento senza DB, svuotata dopo le scritture."""
from datetime import datetime, timedelta, timezone

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import cache_dati
import componenti
import pytest
from ayuda_app import PAGINA_DETTAGLIO, avvia, sessione_db, url_db
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
    at.text_input(key="quota_12").set_value("3,00").run()
    assert not at.exception
    assert len(chiamate) == 1  # le quote stanno in sessione: niente query


ORA = datetime(2026, 11, 5, 10, 20, tzinfo=timezone.utc)  # tempo fisso: niente flakiness


def test_partite_cache_per_ora_intera_e_filtro_su_adesso(sessione_db, monkeypatch):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = ORA + timedelta(minutes=20)  # 10:40
    chiamate = _contatore(monkeypatch, "prossime_partite")
    campionati = (135,)
    _, _, righe = cache_dati.pagina_partite(ORA, campionati)
    assert [r.id for r in righe] == [PARTITA_FUTURA]
    # 15 minuti dopo (stessa ora): dalla cache, partita ancora da giocare
    _, _, righe = cache_dati.pagina_partite(ORA + timedelta(minutes=15), campionati)
    assert [r.id for r in righe] == [PARTITA_FUTURA]
    # 30 minuti dopo (ancora stessa ora, dalla cache): la partita e' iniziata, esce dall'elenco
    _, _, righe = cache_dati.pagina_partite(ORA + timedelta(minutes=30), campionati)
    assert righe == []
    assert len(chiamate) == 1
    # l'ora dopo: nuova chiave
    cache_dati.pagina_partite(ORA + timedelta(hours=1), campionati)
    assert len(chiamate) == 2


def test_partita_mancante_non_resta_in_cache(sessione_db):
    with sessione_db() as s:
        popola(s)
    assert cache_dati.pagina_dettaglio(777) is None
    with sessione_db() as s:
        s.add(Partita(id=777, data_utc=ORA + timedelta(days=1), competizione_id=135,
                      stagione=2026, giornata=8, casa_id=1, trasferta_id=2, stato="NS"))
    assert cache_dati.pagina_dettaglio(777) is not None


def test_calendario_e_turno_secondo_caricamento_dalla_cache(sessione_db, monkeypatch):
    import componenti_calendario

    with sessione_db() as s:
        popola(s)
    chiamate = []
    for nome in ("carica_calendario", "righe_turno"):
        originale = getattr(componenti_calendario, nome)

        def contato(*args, _o=originale, **kwargs):
            chiamate.append(1)
            return _o(*args, **kwargs)

        monkeypatch.setattr(componenti_calendario, nome, contato)
    for _ in range(2):
        calendario = cache_dati.calendario(135)
        assert len(cache_dati.righe_turno(calendario.turni[-1])) == 1
    assert len(chiamate) == 2  # una lettura del calendario e una del turno, non quattro
