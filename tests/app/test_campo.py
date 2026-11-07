"""Campo con le formazioni nel Dettaglio: posizioni, colori, numeri, panchine, escape."""
import re

import pytest
from ayuda_app import PAGINA_DETTAGLIO, avvia, sessione_db, url_db  # noqa: F401
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola, popola_panchina

import campo  # noqa: E402  (app/ è in sys.path grazie ad ayuda_app)
import componenti  # noqa: E402
import componenti_campo as cc  # noqa: E402
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra
from ammonizioni.motore.tipi import Titolare

LOGO = "https://a.espncdn.com/i/teamlogos/soccer/500/2572.png"
FOTO_12 = "https://r2.thesportsdb.com/images/media/player/cutout/dodici.png"


@pytest.mark.parametrize("p,livello", [
    (None, "neutro"), (0.0, "verde"), (0.149, "verde"), (0.15, "giallo"), (0.30, "giallo"),
    (0.301, "rosso"), (0.7, "rosso"),
])
def test_bordo_per_soglia_di_rischio(p, livello):
    assert cc.livello_rischio(p) == livello


@pytest.mark.parametrize("nome,atteso", [
    ("Lautaro Martínez", "Martínez"), ("Matthijs de Ligt", "de Ligt"), ("Pedri", "Pedri"),
    ("Kevin De Bruyne", "De Bruyne"), ("Vinícius Júnior", "Júnior"),
])
def test_cognome(nome, atteso):
    assert cc.cognome(nome) == atteso


def _t(gid, griglia, ruolo="M"):
    return Titolare(gid, f"G{gid}", 1, ruolo, griglia, None)


def test_posizioni_dalla_griglia_e_modulo():
    # 4-3-3 dato in disordine; un giocatore senza griglia va nella riga del suo ruolo
    titolari = [
        _t(1, "1:1", "G"), _t(5, "2:4"), _t(2, "2:1"), _t(4, "2:3"), _t(3, "2:2"),
        _t(6, "3:1"), _t(7, "3:2"), _t(8, None, "M"), _t(9, "5:1"), _t(10, "5:2"), _t(11, "5:3"),
    ]
    pos = cc.posizioni(titolari)
    assert pos[1] == (1, 1, 1)
    assert [pos[i] for i in (2, 3, 4, 5)] == [(2, 1, 4), (2, 2, 4), (2, 3, 4), (2, 4, 4)]
    assert pos[8] == (3, 3, 3)  # dopo chi ha la griglia
    assert cc.modulo(pos) == "4-3-3"
    con_trequarti = cc.posizioni([_t(1, "1:1", "G"), _t(2, "2:1"), _t(3, "3:1"), _t(4, "4:1"), _t(5, "5:1")])
    assert cc.modulo(con_trequarti) == "1-1-1-1"
    # griglie doppie o fuori scala non sovrappongono nessuno
    pos = cc.posizioni([_t(1, "2:1"), _t(2, "2:1"), _t(3, "9:9", "F")])
    assert {pos[1][1], pos[2][1]} == {1, 2} and pos[3][0] == 5


def test_coordinate_specchiate_casa_sinistra_trasferta_destra():
    # orizzontale: la colonna 1 (destra) della casa è in basso, quella della trasferta in alto
    x1, y1 = campo.coordinate(2, 1, 4, casa=True, verticale=False)
    x4, y4 = campo.coordinate(2, 4, 4, casa=True, verticale=False)
    assert x1 < campo.LARGO / 2 and y1 > y4
    xt, yt = campo.coordinate(2, 1, 4, casa=False, verticale=False)
    assert xt > campo.LARGO / 2 and yt < campo.ALTO / 2
    assert campo.coordinate(1, 1, 1, True, False)[0] < campo.coordinate(5, 1, 1, True, False)[0]
    # verticale: casa sotto, trasferta sopra; la destra della casa è a destra
    xv, yv = campo.coordinate(2, 1, 4, casa=True, verticale=True)
    assert yv > campo.LARGO / 2 and xv > campo.ALTO / 2
    assert campo.coordinate(2, 1, 4, casa=False, verticale=True)[1] < campo.LARGO / 2


def _prepara(s, ufficiali=True):
    popola(s, con_formazione=ufficiali)
    popola_panchina(s, salvata=ufficiali)
    casa = s.get(Squadra, CASA)
    casa.colore, casa.colore_alt, casa.logo_url = "#0057B8", "#FFFFFF", LOGO
    if ufficiali:
        s.get(Formazione, (PARTITA_FUTURA, CASA, 12, "ufficiale")).maglia = 2
        s.get(Formazione, (PARTITA_FUTURA, CASA, 15, "panchina")).maglia = 19
    s.get(Giocatore, 12).foto_url = FOTO_12
    s.get(Presenza, (6, 13)).maglia = 8 # nessuna maglia in formazione: dall'ultima presenza
    s.get(Presenza, (1, 13)).maglia = 30  # più vecchia: non conta
    s.flush()


def _campo(s):
    return componenti.carica_pagina_dettaglio(s, PARTITA_FUTURA).campo


def test_campo_con_le_ufficiali(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        dati = _campo(s)
    assert dati.ufficiali
    assert (dati.casa.nome, dati.casa.colore, dati.casa.logo) == ("Casa FC", "#0057B8", LOGO)
    casa = {g.id: g for g in dati.casa.titolari}
    assert set(casa) == {11, 12, 13, 14}
    # posizioni coerenti con la griglia salvata (riga:colonna)
    assert (casa[11].riga, casa[12].riga, casa[13].riga, casa[14].riga) == (1, 2, 3, 4)
    assert dati.casa.modulo == "1-1-1"
    assert casa[12].numero == 2 and casa[13].numero == 8 and casa[11].numero is None
    assert casa[12].avversario_id is not None and casa[11].probabilita is None  # portiere
    assert casa[12].volto == FOTO_12
    assert casa[11].volto is None  # senza foto salvata: niente URL (resta la maglietta)
    # panchina ufficiale completa (anche chi non entra mai), con il numero
    panca = {g.id: g for g in dati.casa.panchina}
    assert set(panca) == {15, 16, 17} and panca[15].numero == 19
    assert {g.id for g in dati.trasferta.panchina} == {25}


def test_campo_con_le_probabili_mostra_i_probabili_subentranti(sessione_db):
    with sessione_db() as s:
        _prepara(s, ufficiali=False)
        dati = _campo(s)
    assert not dati.ufficiali
    assert len(dati.casa.titolari) == 4
    panca = {g.id: g for g in dati.casa.panchina}
    assert set(panca) == {15}  # solo chi entra davvero
    assert panca[15].probabilita is not None


def test_immagini_spente_niente_volti_ne_stemmi(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        componenti.imposta_immagini(s, False)
        dati = _campo(s)
    assert dati.casa.logo is None
    assert all(g.volto is None for g in dati.casa.titolari + dati.casa.panchina)
    assert "cr-volto" not in campo.campo_html(dati)


def test_probabilita_invariate_con_maglie_colori_e_stemmi(sessione_db):
    with sessione_db() as s:
        popola(s)
        popola_panchina(s)
        prima = {c.giocatore_id: c.probabilita for c in componenti.carica_dettaglio(s, PARTITA_FUTURA, {}).candidati}
    with sessione_db() as s:
        for sq in (CASA, TRASF):
            q = s.get(Squadra, sq)
            q.colore, q.logo_url = "#123456", LOGO
        for p in s.query(Presenza).all():
            p.maglia = 7
        for f in s.query(Formazione).all():
            f.maglia = 9
        componenti.imposta_immagini(s, True)
    with sessione_db() as s:
        dopo = {c.giocatore_id: c.probabilita for c in componenti.carica_dettaglio(s, PARTITA_FUTURA, {}).candidati}
    assert dopo == prima


def test_rendering_svg_con_ancore_colori_ed_escape(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        s.get(Partita, PARTITA_FUTURA)  # noqa: B018
        from ammonizioni.db.modelli import Giocatore
        s.get(Giocatore, 14).nome = 'Punta <script>alert("x")</script>'
        s.get(Squadra, TRASF).nome = "Trasf & <b>Co</b>"
    with sessione_db() as s:
        dati = _campo(s)
    html = campo.campo_html(dati)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Trasf &amp; &lt;b&gt;Co&lt;/b&gt;" in html
    assert html.count('href="#cand-12"') == 2  # orizzontale e verticale
    assert 'class="cr-campo-o"' in html and 'class="cr-campo-v"' in html
    assert "#0057B8" in html  # maglia nei colori ESPN
    assert "Formazioni ufficiali" in html
    assert f'src="{LOGO}"' in html
    # volto come sfondo CSS (una foto mancante non mostra l'icona dell'immagine rotta)
    assert f"background-image:url('{FOTO_12}')" in html
    assert "<image" not in html
    # bordo per soglia: classi coerenti con le probabilità
    for g in dati.casa.titolari:
        assert f"cr-pl-{g.id} cr-rischio--{cc.livello_rischio(g.probabilita)}" in html
    css = campo.campo_css(dati)
    g12 = next(g for g in dati.casa.titolari if g.id == 12)
    assert f"body:has(#cand-12:target) .cr-dl-12" in css
    assert f"body:has(#cand-12:target) .cr-pl-{g12.avversario_id} .cr-maglia" in css
    # la linea del duello unisce le due magliette
    assert re.search(r'class="cr-duello cr-dl-12" x1="\d+" y1="\d+" x2="\d+" y2="\d+"', html)


def test_colori_simili_la_trasferta_usa_l_alternativo():
    base = dict(logo=None, modulo="", titolari=(), panchina=())
    casa = cc.SquadraCampo(1, "A", "#FFFFFF", None, **base)
    trasf = cc.SquadraCampo(2, "B", "#FAFAFA", "#C8102E", **base)
    assert campo.colori_squadre(casa, trasf) == ("#FFFFFF", "#C8102E")
    senza = cc.SquadraCampo(3, "C", None, None, **base)
    c, t = campo.colori_squadre(senza, senza)
    assert re.fullmatch(r"#[0-9A-F]{6}", c)  # colore ricavato dal nome
    assert campo.colore_numero("#FFFFFF") == "#15171C" and campo.colore_numero("#000000") == "#FFFFFF"
    # rosso e blu (luminosità simile) restano distinti: conta la tinta
    rossi = cc.SquadraCampo(4, "D", "#FB090B", "#000000", **base)
    blu = cc.SquadraCampo(5, "E", "#0068A8", "#000000", **base)
    assert campo.colori_squadre(blu, rossi) == ("#0068A8", "#FB090B")


@pytest.mark.parametrize("valore,atteso", [
    ("#0068a8", "#0068A8"), ('#000" onload="x', None), ("red", None), (None, None),
])
def test_colore_valido_prima_di_finire_nell_svg(valore, atteso):
    assert cc.colore_valido(valore) == atteso


def test_pagina_dettaglio_mostra_il_campo_e_le_ancore(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    testi = [m.value for m in at.markdown]
    assert any('class="cr-campo"' in t for t in testi)
    assert any('id="cand-12"' in t for t in testi)  # ancora sulla barra del candidato
