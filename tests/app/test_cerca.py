"""Pagina Cerca: ricerca, scheda del giocatore, partite della squadra, filtro campionato."""
from datetime import datetime, timedelta, timezone

from ayuda_app import (  # noqa: F401
    PAGINA_CERCA, PAGINA_PARTITE, RADICE, avvia, campionato_scelto, scegli_campionato,
    sessione_db, url_db, visibile,
)
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola

from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra

CALHA = 500
LIGA = 900


def _prepara(sessione_db, *, liga=False):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(days=2)
        s.add(Giocatore(id=CALHA, nome="Hakan Çalhanoğlu", ruolo="M"))
        s.add(Giocatore(id=501, nome="<script>alert(1)</script>", ruolo="D"))
        s.flush()
        s.add(Presenza(partita_id=1, giocatore_id=CALHA, squadra_id=CASA, minuti=0, gialli=1))
        s.add(Presenza(partita_id=2, giocatore_id=CALHA, squadra_id=CASA, minuti=90, gialli=0,
                       falli_commessi=2))
        s.add(Presenza(partita_id=1, giocatore_id=501, squadra_id=CASA, minuti=10))
        if liga:
            s.add_all([Squadra(id=601, nome="Real Liga"), Squadra(id=602, nome="Barca Liga")])
            s.flush()
            s.add(Partita(id=LIGA, data_utc=datetime.now(timezone.utc) + timedelta(days=3),
                          competizione_id=140, stagione=2026, giornata=11, casa_id=601,
                          trasferta_id=602, stato="NS"))


def _cerca(at, testo):
    at.text_input(key="cerca_testo").set_value(testo).run()
    return at


def test_pagina_vuota_invita_a_scrivere(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CERCA)
    assert not at.exception
    assert "almeno due lettere" in visibile(at)


def test_ricerca_senza_accenti_trova_il_giocatore(sessione_db):
    _prepara(sessione_db)
    at = _cerca(avvia(PAGINA_CERCA), "calhanoglu")
    assert not at.exception
    t = visibile(at)
    assert "Hakan Çalhanoğlu" in t and "Casa FC" in t and "Centrocampista" in t
    assert "Giocatori" in [h.value for h in at.subheader]
    assert "Squadre" not in [h.value for h in at.subheader]


def test_giocatori_e_squadre_in_gruppi_separati(sessione_db):
    _prepara(sessione_db)
    at = _cerca(avvia(PAGINA_CERCA), "casa")
    sotto = [h.value for h in at.subheader]
    assert "Giocatori" in sotto and "Squadre" in sotto
    assert sotto.index("Giocatori") < sotto.index("Squadre")


def test_nomi_con_html_sono_escapati(sessione_db):
    _prepara(sessione_db)
    at = _cerca(avvia(PAGINA_CERCA), "script")
    html = "\n".join(m.value for m in at.markdown)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_nessun_risultato(sessione_db):
    _prepara(sessione_db)
    assert "Nessun risultato" in visibile(_cerca(avvia(PAGINA_CERCA), "zzzz"))


def test_scheda_giocatore_con_giallo_dalla_panchina(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CERCA, giocatore=CALHA)
    assert not at.exception
    t = visibile(at)
    assert "Hakan Çalhanoğlu" in t
    assert "Prossima partita" in t and "Statistiche per stagione" in t and "Ultime partite" in t
    html = "\n".join(m.value for m in at.markdown)
    assert "cr-tabella" in html
    # una presenza (la panchina a 0 minuti non conta), 90 minuti, un giallo
    assert "<td>2026</td><td>Serie A</td><td>1</td><td>90</td><td>1</td>" in html


def test_scheda_titolare_mostra_probabilita_e_arbitro(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CERCA, giocatore=12)
    assert not at.exception
    t = visibile(at)
    assert "Casa FC – Trasferta FC" in t
    assert "Arbitro: Rossi" in t and "Contro Trasferta FC" in t
    assert any("cr-candidato" in m.value for m in at.markdown)


def test_giocatore_inesistente(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CERCA, giocatore=99999)
    assert not at.exception and "Giocatore non trovato" in visibile(at)


def test_scheda_squadra_con_partite_in_programma(sessione_db):
    _prepara(sessione_db)
    with sessione_db() as s:
        s.add(Partita(id=300, data_utc=datetime.now(timezone.utc) + timedelta(days=9),
                      competizione_id=135, stagione=2026, giornata=9, casa_id=TRASF,
                      trasferta_id=CASA, stato="NS"))
    at = avvia(PAGINA_CERCA, squadra=CASA)
    assert not at.exception
    t = visibile(at)
    assert "Casa FC" in t
    schede = [m.value for m in at.markdown if 'class="cr-partita"' in m.value]
    assert len(schede) == 2
    assert "Giornata 7" in schede[0] and "Giornata 9" in schede[1]  # in ordine di data


def test_squadra_inesistente(sessione_db):
    _prepara(sessione_db)
    assert "Squadra non trovata" in visibile(avvia(PAGINA_CERCA, squadra=99999))


def test_squadra_senza_partite(sessione_db):
    _prepara(sessione_db)
    with sessione_db() as s:
        s.add(Squadra(id=700, nome="Squadra Ferma"))
    assert "Nessuna partita in programma" in visibile(avvia(PAGINA_CERCA, squadra=700))


def test_i_pulsanti_del_campionato_filtrano_le_squadre(sessione_db):
    _prepara(sessione_db, liga=True)
    at = _cerca(avvia(PAGINA_CERCA), "liga")
    assert campionato_scelto(at) == "Serie A"
    t = visibile(at)
    assert "Real Liga" not in t and "2 squadre di altri campionati" in t
    scegli_campionato(at, "Liga")
    assert "Real Liga" in visibile(at) and "Barca Liga" in visibile(at)
    scegli_campionato(at, "Tutti")
    assert "Real Liga" in visibile(at)


def test_i_giocatori_non_dipendono_dal_filtro(sessione_db):
    _prepara(sessione_db, liga=True)
    at = avvia(PAGINA_CERCA)
    scegli_campionato(at, "Liga")
    assert "Hakan Çalhanoğlu" in visibile(_cerca(at, "calhanoglu"))


def test_cerca_e_nel_menu_nell_ordine_giusto():
    testo = (RADICE / "app" / "Partite.py").read_text(encoding="utf-8")
    ordine = [testo.index(f'title="{t}"') for t in ("Partite", "Cerca", "Giocate", "Impostazioni")]
    assert ordine == sorted(ordine)


def test_navigazione_verso_cerca(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    for pagina in ("pagine/4_Cerca.py", "pagine/2_Giocate.py", "pagine/4_Cerca.py"):
        at.switch_page(pagina).run()
        assert not at.exception, pagina
