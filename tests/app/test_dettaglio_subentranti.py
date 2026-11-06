"""Probabili subentranti nella pagina Dettaglio: tabella a parte sotto i titolari."""
from dataclasses import replace

from ayuda_app import PAGINA_DETTAGLIO, avvia, sessione_db, url_db, visibile  # noqa: F401
from db_prova import PARTITA_FUTURA, popola, popola_panchina

import componenti
import stile
from ammonizioni.motore.tipi import Candidato, InfoSubentro


def _subentrante(**kw):
    info = dict(
        probabilita_ingresso=0.62, minuti_medi=24.4, panchine=10, ingressi=6,
        al_posto_di_id=7, al_posto_di_nome="Titolare <b>Uno</b>", gialli90=0.31,
        falli90=2.4, media_gialli90=0.12, media_falli90=1.1, sopra_media=True, sfavorita=False,
    )
    info.update(kw)
    return Candidato(
        giocatore_id=9, nome="Riserva & Co", squadra_id=1, ruolo="F", probabilita=0.05,
        motivazioni=[], affidabilita="medio", avversario_diretto_id=None, fattori=[],
        quota=None, prob_implicita=None, valore=None, subentro=InfoSubentro(**info),
    )


def test_etichetta_e_medie_del_subentrante():
    c = _subentrante()
    assert componenti.etichetta_subentro(c) == (
        "subentrante · può entrare al posto di Titolare <b>Uno</b>")
    senza = _subentrante(al_posto_di_id=None, al_posto_di_nome=None)
    assert componenti.etichetta_subentro(senza) == "subentrante · può entrare"
    assert componenti.medie_subentro(c) == (
        "Gialli 90' 0,31 (ruolo 0,12) · Falli 90' 2,4 (ruolo 1,1)")
    assert componenti.ingresso_subentro(c) == "Entra 62% · 24' di media"
    assert "n.d." in componenti.medie_subentro(_subentrante(gialli90=None, falli90=None))


def test_barra_del_subentrante_con_escape_ed_evidenza():
    html = stile.barra_probabilita(_subentrante(), "Casa <FC>")
    assert "cr-subentrante" in html
    assert "Titolare &lt;b&gt;Uno&lt;/b&gt;" in html and "<b>Uno" not in html
    assert "Riserva &amp; Co" in html and "Casa &lt;FC&gt;" in html
    assert "Sopra la media" in html
    sotto = stile.barra_probabilita(_subentrante(sopra_media=False), "Casa")
    assert "Sopra la media" not in sotto
    # i titolari non cambiano aspetto
    titolare = stile.barra_probabilita(replace(_subentrante(), subentro=None), "Casa")
    assert "cr-subentrante" not in titolare and "subentrante" not in titolare


def test_righe_subentranti():
    righe = componenti.righe_subentranti([_subentrante()], {1: "Casa"})
    assert list(righe[0]) == list(componenti.COLONNE_SUBENTRANTI)
    assert righe[0]["Al posto di"] == "Titolare <b>Uno</b>"  # st.dataframe non interpreta HTML
    assert righe[0]["Sopra la media"] == "sì" and righe[0]["Entra"] == "62%"


def test_pagina_mostra_i_subentranti_sotto_i_titolari(sessione_db):
    with sessione_db() as s:
        popola(s)
        popola_panchina(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    sottotitoli = [h.value for h in at.subheader]
    assert sottotitoli.index("Candidati all'ammonizione") < sottotitoli.index(
        "Probabili subentranti") < sottotitoli.index("Duelli, storia e quote")
    # tabella dei titolari invariata, tabella dei subentranti a parte
    titolari = at.dataframe[0].value
    assert "Punta Riserva Casa" not in set(titolari["Giocatore"])
    sub = at.dataframe[1].value
    assert list(sub.columns) == list(componenti.COLONNE_SUBENTRANTI)
    assert set(sub["Giocatore"]) == {"Punta Riserva Casa", "Mediano Riserva Trasf"}
    riga = sub[sub["Giocatore"] == "Punta Riserva Casa"].iloc[0]
    assert riga["Al posto di"] == "Punta Casa"
    t = visibile(at)
    assert "Terzo Portiere Casa" not in t and "Difensore Mai Casa" not in t
    assert "può entrare al posto di Punta Casa" in t


def test_pagina_senza_panchina_nessuna_sezione(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    assert "Probabili subentranti" not in [h.value for h in at.subheader]
    assert len(at.dataframe) == 1


# --- affidabilità: ordinamento e puntata più solida -----------------------------


def _cand(i, prob, punti):
    return replace(_subentrante(), giocatore_id=i, nome=f"G{i}", probabilita=prob,
                   affidabilita_punti=punti, subentro=None)


def test_ordina_per_probabilita_o_per_affidabilita():
    cs = [_cand(1, 0.30, 50), _cand(2, 0.25, 90), _cand(3, 0.20, 90), _cand(4, 0.10, 20)]
    assert [c.giocatore_id for c in componenti.ordina_candidati(cs, False)] == [1, 2, 3, 4]
    assert [c.giocatore_id for c in componenti.ordina_candidati(cs, True)] == [2, 3, 1, 4]


def test_puntata_piu_solida_serve_affidabilita_alta_e_probabilita_vicina_alla_migliore():
    assert componenti.puntata_piu_solida([]) is None
    # il più probabile è poco affidabile: vince il secondo (alta affidabilità, prob. >= metà)
    cs = [_cand(1, 0.40, 55), _cand(2, 0.30, 85), _cand(3, 0.10, 99)]
    assert componenti.puntata_piu_solida(cs).giocatore_id == 2
    # affidabile ma troppo improbabile (meno di metà della migliore): escluso
    assert componenti.puntata_piu_solida([_cand(1, 0.40, 60), _cand(3, 0.10, 99)]) is None
    # nessuno con affidabilità alta
    assert componenti.puntata_piu_solida([_cand(1, 0.40, 69), _cand(2, 0.35, 40)]) is None
    # più candidati adatti: il maggior prodotto probabilità x affidabilità
    assert componenti.puntata_piu_solida([_cand(1, 0.40, 70), _cand(2, 0.38, 90)]).giocatore_id == 2


def test_dettaglio_mostra_la_puntata_piu_solida_se_c_e(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert html.count("Puntata più solida") <= 1
    if "Puntata più solida" in html:
        assert html.index("Puntata più solida") < html.index("cr-candidato")
