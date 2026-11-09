"""Stemmi ESPN al posto delle iniziali e impostazione "Immagini da ESPN"."""
from datetime import datetime, timedelta, timezone

from ayuda_app import PAGINA_IMPOSTAZIONI, PAGINA_PARTITE, avvia, sessione_db, url_db  # noqa: F401
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola
from sqlalchemy import select

import componenti  # noqa: E402  (app/ è in sys.path grazie ad ayuda_app)
import componenti_cerca  # noqa: E402
import stile  # noqa: E402
from ammonizioni.db.modelli import Partita, Squadra

LOGO = "https://a.espncdn.com/i/teamlogos/soccer/500/2572.png"


def test_stemma_immagine_con_alt_dimensioni_e_lazy():
    html = stile.stemma('Como "1907"', LOGO)
    assert html.startswith("<img ") and f'src="{LOGO}"' in html
    assert 'alt="Como &quot;1907&quot;"' in html
    assert 'width="30" height="30"' in html and 'loading="lazy"' in html
    assert 'width="20"' in stile.stemma("Como", LOGO, "mini")


def test_stemma_senza_logo_o_con_url_non_https_usa_le_iniziali():
    for logo in (None, "", "http://x/y.png", 'javascript:alert("x")'):
        html = stile.stemma("Casa FC", logo)
        assert "<img" not in html and ">CF<" in html


def test_url_dello_stemma_con_escape():
    html = stile.stemma("A", 'https://x.example/a.png" onerror="alert(1)')
    assert 'onerror="' not in html and "&quot; onerror=&quot;" in html


def _riga(**campi):
    base = dict(
        id=1, quando="", giornata=3, casa="Como", trasferta="Venezia", arbitro=None, calda=False,
        formazioni="probabili", ora="15:00",
    )
    return componenti.RigaPartita(**{**base, **campi})


def test_scheda_partita_e_menu_con_gli_stemmi():
    riga = _riga(logo_casa=LOGO)
    scheda = stile.scheda_partita(riga)
    assert f'src="{LOGO}"' in scheda and ">VE<" in scheda  # Venezia senza stemma: iniziali
    assert f'src="{LOGO}"' in stile.voce_menu(riga)


def test_riquadro_home_e_ricerca_con_gli_stemmi():
    html = stile.riquadro_home("Partita più calda", "Como – Venezia", squadre=(("Como", LOGO), ("Venezia", None)))
    assert f'src="{LOGO}"' in html and ">VE<" in html
    assert f'src="{LOGO}"' in stile.risultato_ricerca("Como", "Squadra", LOGO, squadra=True)
    assert "<img" not in stile.risultato_ricerca("Mario", "Como")
    assert f'src="{LOGO}"' in stile.titolo_squadra("Como", LOGO)


def _con_stemma(s):
    popola(s)
    s.get(Squadra, CASA).logo_url = LOGO
    s.get(Squadra, TRASF).logo_url = "http://insicuro.example/x.png"
    s.flush()


def test_righe_partite_con_stemmi_solo_se_le_immagini_sono_accese(sessione_db):
    with sessione_db() as s:
        _con_stemma(s)
        partite = list(s.scalars(select(Partita).where(Partita.id == PARTITA_FUTURA)))
        (riga,) = componenti.righe_partite(s, partite)
        assert (riga.logo_casa, riga.logo_trasferta) == (LOGO, None)
        assert componenti.immagini_attive(s)  # accese di default
        squadre = {q.id: q for q in componenti_cerca.carica_indice(s).squadre}
        assert squadre[CASA].logo == LOGO
        componenti.imposta_immagini(s, False)
        (riga,) = componenti.righe_partite(s, partite)
        assert riga.logo_casa is None
        assert componenti_cerca.carica_indice(s).squadre[0].logo is None


def test_impostazione_immagini_accesa_di_default_e_spegnibile(sessione_db):
    with sessione_db() as s:
        _con_stemma(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    interruttore = at.toggle(key="immagini_espn")
    assert interruttore.value is True
    assert "solo uso personale" in interruttore.label
    assert any("protette da diritti" in c.value for c in at.caption)
    interruttore.set_value(False).run()
    assert not at.exception
    with sessione_db() as s:
        assert componenti.immagini_attive(s) is False


def test_pagina_partite_mostra_lo_stemma(sessione_db):
    with sessione_db() as s:
        _con_stemma(s)
        # la pagina mostra i prossimi 7 giorni dall'orologio vero: la data fissa scadrebbe
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(days=1)
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    assert any(f'src="{LOGO}"' in m.value for m in at.markdown)
