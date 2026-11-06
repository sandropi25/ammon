"""Riquadro "Scommetti" nella scheda del giocatore: valore della quota e "L'ho giocata"."""
from datetime import date

import pytest
from ayuda_app import PAGINA_DETTAGLIO, avvia, sessione_db, url_db  # noqa: F401
from db_prova import PARTITA_FUTURA, popola
from sqlalchemy import select

import componenti  # noqa: E402  (app/ è in sys.path grazie ad ayuda_app)
import componenti_giocate as cg  # noqa: E402
import stile  # noqa: E402
from ammonizioni.db.modelli import Giocata


@pytest.fixture(autouse=True)
def _cache_pulita():
    import streamlit as st

    st.cache_data.clear()
    yield
    st.cache_data.clear()


def test_valore_positivo_e_negativo():
    v = cg.valuta_quota(0.30, 4.5)  # bookmaker 22%, modello 30%
    assert v.conviene and v.testo == "Conviene · valore +8%"
    assert round(v.prob_bookmaker, 4) == round(1 / 4.5, 4)
    v = cg.valuta_quota(0.20, 4.0)  # bookmaker 25%
    assert not v.conviene and v.testo == "Non conviene · −5%"
    html = stile.riquadro_scommetti(v)
    assert "25%" in html and "20%" in html and "cr-badge--rosso" in html
    assert "cr-badge--verde" in stile.riquadro_scommetti(cg.valuta_quota(0.5, 3.0))


def test_testo_della_giocata_registrata():
    assert cg.testo_giocata(10.0, 4.5) == "Giocata registrata: 10 € a 4,50"
    assert cg.testo_giocata(7.5, 2.0) == "Giocata registrata: 7,50 € a 2,00"


def test_registrazione_e_blocco_del_doppione(sessione_db):
    with sessione_db() as s:
        popola(s)
        g = cg.registra_scommessa(s, PARTITA_FUTURA, 12, 4.5, "10", date(2026, 11, 6))
        assert (g.fonte, g.quota, g.puntata, g.esito) == ("io", 4.5, 10.0, "in_attesa")
        with pytest.raises(ValueError, match="già registrato"):
            cg.registra_scommessa(s, PARTITA_FUTURA, 12, 3.0, "5", date(2026, 11, 6))
        with pytest.raises(ValueError, match="Puntata non valida"):
            cg.registra_scommessa(s, PARTITA_FUTURA, 13, 3.0, "zero", date(2026, 11, 6))
        assert componenti.giocate_partita(s, PARTITA_FUTURA) == {12: (10.0, 4.5)}


def test_pagina_quota_badge_e_l_ho_giocata(sessione_db, monkeypatch):
    with sessione_db() as s:
        popola(s)
    chiamate = []
    originale = componenti.carica_pagina_dettaglio
    monkeypatch.setattr(
        componenti, "carica_pagina_dettaglio",
        lambda *a, **k: chiamate.append(1) or originale(*a, **k),
    )
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    # senza quota niente pulsante
    assert "giocata_12" not in {b.key for b in at.button}
    at.text_input(key="quota_12").set_value("100").run()  # 1%: conviene di sicuro
    assert not at.exception and not at.error
    assert any("Conviene · valore +" in m.value for m in at.markdown)
    at.button(key="giocata_12").click().run()
    at.text_input(key="puntata_12").set_value("10")
    at.button(key="conferma_giocata_12").click().run()
    assert not at.exception, at.exception
    with sessione_db() as s:
        g = s.execute(select(Giocata)).scalar_one()
        assert (g.partita_id, g.giocatore_id, g.fonte, g.quota, g.puntata) == (
            PARTITA_FUTURA, 12, "io", 100.0, 10.0,
        )
    assert len(chiamate) == 2  # cache svuotata dopo la scrittura: pagina riletta
    assert any(m.value == "Giocata registrata: 10 € a 100,00" for m in at.success)
    assert "giocata_12" not in {b.key for b in at.button}  # niente doppione dal riquadro


def test_pagina_quota_non_conveniente_e_non_valida(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    at.text_input(key="quota_12").set_value("1,01").run()  # 99%: non conviene
    assert any("Non conviene · −" in m.value for m in at.markdown)
    at.text_input(key="quota_12").set_value("abc").run()
    assert any("Quota non valida" in e.value for e in at.error)
    assert "giocata_12" not in {b.key for b in at.button}
