"""Grafica "Cartellino": componenti HTML (dati attesi, escape), tema chiaro/scuro con il
pulsante sole/luna, pulsanti dei campionati condivisi fra le pagine."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import ayuda_app  # noqa: F401  (aggiunge app/ e tests/motore a sys.path)
import pytest
import stile
from ayuda_app import (
    PAGINA_GIOCATE, PAGINA_IMPOSTAZIONI, PAGINA_PARTITE, RADICE, avvia, campionato_scelto,
    scegli_campionato, sessione_db, url_db, visibile,
)
from componenti import RigaPartita
from db_prova import PARTITA_FUTURA, popola

from ammonizioni.db.modelli import Partita
from ammonizioni.motore.tipi import Candidato


# ---------------------------------------------------------------- palette e sfondo

def test_nome_app_in_un_punto_solo():
    assert stile.NOME_APP == "Cartellino"


@pytest.mark.parametrize("tema", ["scuro", "chiaro"])
def test_contrasto_testo_almeno_4_5_in_entrambi_i_temi(tema):
    p = stile.PALETTE[tema]
    for testo in ("testo", "testo2", "link"):
        for fondo in ("sfondo", "superficie"):
            assert stile.contrasto(p[testo], p[fondo]) >= 4.5, (tema, testo, fondo)


def test_palette_del_piano():
    assert stile.PALETTE["scuro"]["sfondo"] == "#0F1115"
    assert stile.PALETTE["chiaro"]["sfondo"] == "#F7F7F5"
    assert stile.PALETTE["scuro"]["giallo"] == "#F5C518"
    assert stile.PALETTE["chiaro"]["rosso"] == "#D1343A"


def test_tema_chiaro_davvero_chiaro():
    css = stile.css_tema("chiaro")
    assert "--cr-sfondo: #F7F7F5" in css and "--cr-testo: #15171C" in css
    assert "color-scheme: light" in css
    scuro = stile.css_tema("scuro")
    assert "--cr-sfondo: #0F1115" in scuro and "color-scheme: dark" in scuro


def test_css_carica_i_font_web():
    css = stile.css_tema("scuro")
    assert css.lstrip().startswith("@import url(")
    assert "Barlow+Condensed" in css and "'Barlow'" in css


def test_sfondo_cartellini_tenue_gialli_e_qualche_rosso():
    # circa il doppio di prima (5,5% e 8%), sempre sotto il 15%
    for tema, (minimo, massimo) in (("scuro", (0.09, 0.15)), ("chiaro", (0.12, 0.15))):
        svg = unquote(stile.sfondo_svg(tema).removeprefix("data:image/svg+xml,"))
        p = stile.PALETTE[tema]
        gialli, rossi = svg.count(p["giallo"]), svg.count(p["rosso"])
        assert gialli > rossi >= 1
        assert minimo <= stile.OPACITA_SFONDO[tema] <= massimo
        assert f'fill-opacity="{stile.OPACITA_SFONDO[tema]}"' in svg
    # stesso seme: stesso disegno; su telefono più rado
    assert stile.sfondo_svg("scuro") == stile.sfondo_svg("scuro")
    fitto = unquote(stile.sfondo_svg("scuro")).count("<rect")
    rado = unquote(stile.sfondo_svg("scuro", telefono=True)).count("<rect")
    assert rado < fitto


def _variabili_3d(html):
    import re

    return [dict(re.findall(r"(--[a-z]+):([^;\"]+)", stile_card))
            for stile_card in re.findall(r'style="([^"]+)"', html)]


@pytest.mark.parametrize("tema", ["scuro", "chiaro"])
def test_sfondo_3d_cartellini_su_livelli_diversi(tema):
    html = stile.sfondo_3d_html(tema)
    assert html == stile.sfondo_3d_html(tema)  # seme fisso
    assert 'aria-hidden="true"' in html and "<script" not in html
    carte = _variabili_3d(html)
    assert 12 <= len(carte) <= 18
    assert html.count("cr-c3d--r") >= 2 and html.count("cr-c3d--g") > html.count("cr-c3d--r")
    durate = [float(c["--d"].rstrip("s")) for c in carte]
    assert all(20 <= d <= 45 for d in durate) and len(set(durate)) > 10
    assert len({c["--ritardo"] for c in carte}) > 10  # ritardi sfalsati
    profondita = [int(c["--z"].rstrip("px")) for c in carte]
    lontano, vicino = carte[profondita.index(min(profondita))], carte[profondita.index(max(profondita))]
    assert float(lontano["--s"]) < float(vicino["--s"])  # i lontani più piccoli...
    assert float(lontano["--b"].rstrip("px")) > float(vicino["--b"].rstrip("px")) == 0  # ...e sfocati
    opacita = [float(c["--o"]) for c in carte]
    assert max(opacita) <= stile.OPACITA_SFONDO[tema] < stile.OPACITA_MASSIMA_SFONDO
    # su telefono resta visibile la metà dispari: i rossi ci sono anche lì
    assert any("cr-c3d--r" in pezzo for pezzo in html.split("<i ")[1::2])


def test_css_sfondo_3d_solo_css_con_prospettiva_movimento_ridotto_e_telefono():
    css = stile.css_sfondo_3d("scuro")
    assert "perspective:" in css and "translate3d" in css and "rotateX" in css and "rotateY" in css
    assert "@keyframes cr-fluttua" in css and "will-change: transform" in css
    assert "linear-gradient" in css  # riflesso lucido
    assert "@media (prefers-reduced-motion: reduce) { .cr-c3d { animation: none; } }" in css
    telefono = css[css.index("@media (max-width: 640px)"):]
    assert ":nth-child(2n) { display: none; }" in telefono and "* 1.6" in telefono
    # nelle animazioni solo transform (niente proprietà che ridisegnano la pagina)
    animazione = css[css.index("@keyframes cr-fluttua"):css.index("@media (max-width")]
    assert "left" not in animazione and "top" not in animazione and "filter" not in animazione
    # colori adattati al tema: sul chiaro più saturi
    assert stile.COLORI_SFONDO_3D["chiaro"]["giallo"] in stile.css_sfondo_3d("chiaro")
    assert stile.COLORI_SFONDO_3D["chiaro"] != stile.COLORI_SFONDO_3D["scuro"]


def test_css_tema_animato_toglie_lo_sfondo_fisso():
    fermo, animato = stile.css_tema("scuro"), stile.css_tema("scuro", animato=True)
    assert "data:image/svg+xml" in fermo and "cr-fluttua" not in fermo
    assert "data:image/svg+xml" not in animato and "cr-fluttua" in animato
    assert "background-image: none" in animato


def test_anim_dal_parametro():
    assert stile.anim_da_parametro(None) is True
    assert stile.anim_da_parametro("1") is True
    assert stile.anim_da_parametro("0") is False and stile.anim_da_parametro("off") is False


def test_sfondo_animato_acceso_di_default_e_spento_dalle_impostazioni(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    assert at.session_state["anim"] is True and "anim" not in at.query_params
    assert any("cr-sfondo3d" in h.proto.body for h in at.get("html"))
    interruttore = at.toggle(key="interruttore_sfondo_animato")
    assert interruttore.label == "Sfondo animato" and interruttore.value is True
    interruttore.set_value(False).run()
    assert at.session_state["anim"] is False and at.query_params.get("anim") == "0"
    assert not any("cr-sfondo3d" in h.proto.body for h in at.get("html"))
    at.toggle(key="interruttore_sfondo_animato").set_value(True).run()
    assert at.session_state["anim"] is True and "anim" not in at.query_params


def test_sfondo_fermo_letto_dall_url(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_PARTITE, anim="0")
    assert not at.exception and at.session_state["anim"] is False
    assert not any("cr-sfondo3d" in h.proto.body for h in at.get("html"))


def test_css_sfondo_fisso_e_schede_arrotondate():
    css = stile.css_tema("scuro")
    assert "background-attachment: fixed" in css
    assert "border-radius: 14px" in css
    assert "@media (max-width: 640px)" in css


# ---------------------------------------------------------------- componenti

def test_badge_escape_e_tipo():
    h = stile.badge("<b>Derby</b>", "rosso")
    assert "&lt;b&gt;Derby&lt;/b&gt;" in h and "<b>" not in h
    assert 'class="cr-badge cr-badge--rosso"' in h
    with pytest.raises(ValueError):
        stile.badge("x", "viola")


def _riga(**kw):
    base = dict(
        id=7, quando="", giornata=12, casa="Inter", trasferta="Milan", arbitro="Doveri",
        calda=True, formazioni="ufficiali", campionato="Serie A", ora="20:45",
        data_utc=datetime(2026, 11, 8, 19, 45, tzinfo=timezone.utc), derby=True,
        arbitro_severo=True,
    )
    base.update(kw)
    return RigaPartita(**base)


def test_scheda_partita_contiene_dati_e_badge():
    h = stile.scheda_partita(_riga())
    for atteso in ("20:45", "Inter", "Milan", "Serie A · Giornata 12", "Arbitro: Doveri",
                   "Partita calda", "Derby", "Arbitro severo", "Formazioni ufficiali",
                   'title="Inter – Milan"'):
        assert atteso in h
    assert "\n" not in h  # una riga sola: il markdown non la spezza


def test_scheda_partita_senza_badge_e_probabili():
    h = stile.scheda_partita(_riga(calda=False, derby=False, arbitro_severo=False,
                                   formazioni="probabili", arbitro=None, giornata=None))
    assert "Formazioni probabili" in h and "Arbitro da designare" in h
    assert "Partita calda" not in h and "Derby" not in h and "Giornata" not in h


def test_scheda_partita_con_media_partita_e_arbitro():
    h = stile.scheda_partita(_riga(media_partita=4.62, media_arbitro=3.67, partite_arbitro=43))
    assert "Media partita 4,6 cartellini" in h
    assert "Media arbitro 3,7 (43 partite)" in h
    senza = stile.scheda_partita(_riga())
    assert "Media partita" not in senza and "Media arbitro" not in senza


def test_righe_partite_hanno_le_medie(sessione_db):
    import componenti
    from sqlalchemy import select

    with sessione_db() as s:
        popola(s)
        futura = s.scalars(select(Partita).where(Partita.stato == "NS")).first()
        riga = componenti.righe_partite(s, [futura])[0]
    # con lo storico di prova la media della partita è calcolata (gialli + rossi attesi)
    assert riga.media_partita is None or riga.media_partita > 0
    assert riga.partite_arbitro >= 0


def test_scheda_partita_escape_dei_nomi():
    h = stile.scheda_partita(_riga(casa="<script>x</script>", trasferta='A "&" B', arbitro="<i>"))
    assert "<script>" not in h and "&lt;script&gt;" in h
    assert "A &quot;&amp;&quot; B" in h
    assert "<i>" not in h


def test_iniziali_degli_stemmi():
    assert stile.iniziali("Casa FC") == "CF"
    assert stile.iniziali("Inter") == "IN"
    assert stile.iniziali("Atlético de Madrid") == "AM"
    assert stile.iniziali("") == "?"


def _candidato(**kw):
    base = dict(
        giocatore_id=1, nome="Nicolò Barella", squadra_id=5, ruolo="M", probabilita=0.35,
        motivazioni=["Tanti falli", "Arbitro severo"], affidabilita="alto",
        affidabilita_punti=86,
        affidabilita_motivi=("2.430 minuti in 3 stagioni", "formazione ufficiale"),
        avversario_diretto_id=None, fattori=[], quota=2.5, prob_implicita=0.4, valore=0.12,
    )
    base.update(kw)
    return Candidato(**base)


def test_barra_probabilita_dati_e_larghezza():
    h = stile.barra_probabilita(_candidato(), "Inter", ["Luca"])
    for atteso in ("Nicolò Barella", "Inter", "Centrocampista", "35%", "Tanti falli · Arbitro severo",
                   "🟢 Alta 86", "Valore +12%", "Quota 2,50", "Luca",
                   "Affidabilità: 2.430 minuti in 3 stagioni · formazione ufficiale"):
        assert atteso in h
    assert '<span class="cr-badge cr-badge--verde">🟢 Alta 86</span>' in h
    assert "width: 50%" in h  # 35% su una scala che arriva al 70%
    assert '<span class="cr-badge cr-badge--verde">Valore +12%</span>' in h
    piena = stile.barra_probabilita(_candidato(probabilita=0.9), "Inter")
    assert "width: 100%" in piena
    minima = stile.barra_probabilita(_candidato(probabilita=0.02), "Inter")
    assert "width: 3%" in minima  # resta visibile


def test_barra_probabilita_valore_negativo_e_senza_quota():
    h = stile.barra_probabilita(_candidato(valore=-0.03), "Inter")
    assert '<span class="cr-badge cr-badge--neutro">Valore -3%</span>' in h
    h = stile.barra_probabilita(_candidato(quota=None, prob_implicita=None, valore=None,
                                           affidabilita="dati insufficienti",
                                           affidabilita_punti=12, affidabilita_motivi=()), "Inter")
    assert "Valore" not in h and "Quota" not in h and "🔴 Bassa 12" in h
    assert "cr-affid" not in h  # senza motivi niente riga di dettaglio


def test_livelli_di_affidabilita_nei_badge():
    for punti, atteso in ((70, "🟢 Alta 70"), (69, "🟡 Media 69"), (40, "🟡 Media 40"),
                          (39, "🔴 Bassa 39")):
        assert atteso in stile.barra_probabilita(_candidato(affidabilita_punti=punti), "Inter")
    assert "cr-badge--giallo\">🟡 Media 55" in stile.barra_probabilita(
        _candidato(affidabilita_punti=55), "Inter")
    assert "cr-badge--rosso\">🔴 Bassa 5" in stile.barra_probabilita(
        _candidato(affidabilita_punti=5), "Inter")


def test_riquadro_puntata_solida():
    h = stile.riquadro_puntata_solida(_candidato(), "Inter")
    for atteso in ("Puntata più solida", "Nicolò Barella", "35%", "🟢 Alta 86", "2.430 minuti"):
        assert atteso in h
    h = stile.riquadro_puntata_solida(
        _candidato(nome="<b>x</b>", affidabilita_motivi=("<i>",)), "<Sq>"
    )
    assert "<b>" not in h and "<i>" not in h and "<Sq>" not in h


def test_barra_probabilita_escape():
    h = stile.barra_probabilita(
        _candidato(nome="<img src=x onerror=alert(1)>", motivazioni=["<b>"]), "<Sq>", ["<t>"]
    )
    assert "<img" not in h and "<b>" not in h and "<Sq>" not in h and "<t>" not in h
    assert "&lt;img" in h


def test_scheda_giocata_e_riquadro_statistiche():
    g = stile.scheda_giocata({
        "Data": "05/11/2026", "Partita": "Inter – <Milan>", "Giocatore": "Barella",
        "Fonte": "io", "Quota": "2,10", "Puntata": "10,00 €", "Esito": "vinta",
    })
    assert "Inter – &lt;Milan&gt;" in g and "Barella" in g and "2,10" in g and "10,00 €" in g
    assert "cr-badge--verde" in g and "vinta" in g
    assert "cr-badge--rosso" in stile.scheda_giocata({"Esito": "persa"})
    r = stile.riquadro_statistiche({
        "Fonte": "io", "Giocate": 2, "Successo": "50%", "Prob. implicita media": "40%",
        "Profitto": "5,00 €", "Rendimento": "25%",
    })
    for atteso in ("io", "Giocate", "2", "Successo", "50%", "Prob. implicita media", "40%",
                   "Profitto", "5,00 €", "Rendimento", "25%"):
        assert atteso in r


def test_scheda_contesto_escape():
    h = stile.scheda_contesto(["Arbitro: <Rossi>", "Rivalità: sì"])
    assert "Arbitro: &lt;Rossi&gt;" in h and "Rivalità: sì" in h


def test_logo_due_cartellini_inclinati():
    svg = stile.logo_svg()
    assert svg.count("<rect") == 2 and "rotate(" in svg


# ---------------------------------------------------------------- parametri URL

def test_tema_e_campionato_dai_parametri():
    assert stile.tema_da_parametro("chiaro") == "chiaro"
    assert stile.tema_da_parametro(None) == "scuro"
    assert stile.tema_da_parametro("boh") == "scuro"
    assert stile.campionato_da_parametro("liga") == "Liga"
    assert stile.campionato_da_parametro("tutti") == "Tutti"
    assert stile.campionato_da_parametro(None) == "Serie A"
    assert stile.campionato_da_parametro("xyz") == "Serie A"
    assert stile.slug_campionato("Serie A") == "serie-a"


# ---------------------------------------------------------------- nelle pagine

def _prepara(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(days=2)


def test_pulsante_sole_luna_alterna_il_tema_e_lo_scrive_nell_url(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    assert at.session_state["tema"] == "scuro"
    assert at.button(key="cambia_tema").label == "☀️"
    at.button(key="cambia_tema").click().run()
    assert at.session_state["tema"] == "chiaro"
    assert at.query_params.get("tema") == "chiaro"
    assert at.button(key="cambia_tema").label == "🌙"
    at.button(key="cambia_tema").click().run()
    assert at.session_state["tema"] == "scuro"
    assert "tema" not in at.query_params


def test_tema_chiaro_letto_dall_url(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE, tema="chiaro")
    assert not at.exception
    assert at.session_state["tema"] == "chiaro"
    assert at.button(key="cambia_tema").label == "🌙"


def test_intestazione_con_nome_app(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    assert "Cartellino" in visibile(at)
    assert "Dati non ancora aggiornati" in visibile(at)


def test_campionato_predefinito_serie_a_e_url(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    assert campionato_scelto(at) == "Serie A"
    assert at.button(key="campionato_tutti").label == "Tutti"
    assert at.query_params.get("campionato") == "serie-a"


def test_campionato_condiviso_tra_le_pagine(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    scegli_campionato(at, "Liga")
    assert at.query_params.get("campionato") == "liga"
    at.switch_page("pagine/2_Giocate.py").run()
    assert not at.exception
    assert campionato_scelto(at) == "Liga"
    at.switch_page("pagine/0_Partite.py").run()
    assert campionato_scelto(at) == "Liga"


def test_campionato_letto_dall_url(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_GIOCATE, campionato="tutti")
    assert not at.exception
    assert campionato_scelto(at) == "Tutti"
    assert at.button(key="campionato_tutti").proto.type == "primary"


def test_navigazione_in_alto_verso_le_pagine(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    for pagina in ("pagine/2_Giocate.py", "pagine/3_Impostazioni.py", "pagine/0_Partite.py"):
        at.switch_page(pagina).run()
        assert not at.exception, pagina


def test_router_usa_la_navigazione_in_alto():
    testo = (RADICE / "app" / "Partite.py").read_text(encoding="utf-8")
    assert '"top" if auth.accesso_valido() else "hidden"' in testo
    assert "st.navigation(pagine, position=menu)" in testo


def test_ogni_pagina_chiama_applica_stile_dopo_la_password():
    radice = RADICE / "app" / "pagine"
    for pagina in sorted(radice.glob("*.py")):
        testo = pagina.read_text(encoding="utf-8")
        assert "applica_stile(" in testo, pagina.name
        assert testo.index("richiedi_password()") < testo.index("applica_stile("), pagina.name


def test_impostazioni_con_stile(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    assert "Cartellino" in visibile(at)


def test_config_tema_scuro_e_font():
    testo = (RADICE / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'base = "dark"' in testo and "Barlow" in testo
    assert Path(stile.__file__).name == "stile.py"
