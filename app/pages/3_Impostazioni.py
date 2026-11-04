"""Impostazioni: derby e campi caldi, pesi del modello e chiave API."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

import componenti_giocate as cg  # noqa: E402
from auth import richiedi_password  # noqa: E402
from ammonizioni.db import repo  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402
from ammonizioni.motore.pesi import Pesi, carica_pesi, salva_pesi  # noqa: E402

st.set_page_config(page_title="Impostazioni", layout="wide")
richiedi_password()

st.title("Impostazioni")

with apri() as s:
    squadre = cg.squadre_serie_a(s)
    derby = cg.voci_lista(s, "derby")
    campi_caldi = cg.voci_lista(s, "campo_caldo")
    pesi = carica_pesi(s)
    chiave_salvata = repo.leggi_impostazione(s, "chiave_api", None)

nomi_squadre = dict(squadre)


def elenco_con_rimozione(voci: list[cg.VoceLista]) -> None:
    if not voci:
        st.caption("Nessuna voce.")
    for voce in voci:
        colonne = st.columns([6, 1])
        colonne[0].markdown(voce.testo)
        if colonne[1].button("Rimuovi", key=f"rimuovi_lista_{voce.id}"):
            with apri() as s:
                cg.rimuovi_voce(s, voce.id)
            st.rerun()


# ---------------------------------------------------------------- derby e campi caldi

st.header("Derby e rivalità")
elenco_con_rimozione(derby)
if len(squadre) < 2:
    st.info("Servono almeno due squadre di Serie A nei dati per aggiungere un derby.")
else:
    colonne = st.columns(2)
    squadra_a = colonne[0].selectbox(
        "Prima squadra", list(nomi_squadre), format_func=lambda i: nomi_squadre[i], key="derby_a"
    )
    squadra_b = colonne[1].selectbox(
        "Seconda squadra", list(nomi_squadre), index=1, format_func=lambda i: nomi_squadre[i],
        key="derby_b",
    )
    if st.button("Aggiungi derby", key="aggiungi_derby"):
        try:
            with apri() as s:
                cg.aggiungi_derby(s, squadra_a, squadra_b)
        except ValueError as errore:
            st.error(str(errore))
        else:
            st.rerun()

st.header("Campi caldi")
elenco_con_rimozione(campi_caldi)
if squadre:
    squadra_calda = st.selectbox(
        "Squadra", list(nomi_squadre), format_func=lambda i: nomi_squadre[i],
        key="campo_caldo_squadra",
    )
    if st.button("Aggiungi campo caldo", key="aggiungi_campo_caldo"):
        try:
            with apri() as s:
                cg.aggiungi_campo_caldo(s, squadra_calda)
        except ValueError as errore:
            st.error(str(errore))
        else:
            st.rerun()

# ---------------------------------------------------------------- pesi

st.header("Pesi del modello")
scalari, nomi_tuple = cg.campi_pesi()
with st.form("form_pesi"):
    valori_scalari: dict[str, float] = {}
    for nome, tipo in scalari:
        corrente = getattr(pesi, nome)
        if tipo is int:
            valori_scalari[nome] = st.number_input(nome, value=int(corrente), step=1, key=f"peso_{nome}")
        else:
            passo = 0.01 if abs(corrente) < 10 else 1.0
            valori_scalari[nome] = st.number_input(
                nome, value=float(corrente), step=passo, format="%g", key=f"peso_{nome}"
            )
    testi_tuple: dict[str, str] = {}
    for nome in nomi_tuple:
        testi_tuple[nome] = st.text_input(
            nome,
            value=cg.testo_tupla(getattr(pesi, nome)),
            help="Valori separati da virgole, con il punto come decimale (es. 0.6, 0.3, 0.1)",
            key=f"peso_{nome}",
        )
    colonne = st.columns(2)
    salva = colonne[0].form_submit_button("Salva", key="salva_pesi")
    ripristina = colonne[1].form_submit_button("Ripristina valori predefiniti", key="ripristina_pesi")

if salva:
    try:
        nuovi = cg.costruisci_pesi(valori_scalari, testi_tuple)
    except ValueError as errore:
        st.error(str(errore))
    else:
        with apri() as s:
            salva_pesi(s, nuovi)
        st.rerun()
if ripristina:
    with apri() as s:
        salva_pesi(s, Pesi())
    for nome, _ in scalari:
        del st.session_state[f"peso_{nome}"]
    for nome in nomi_tuple:
        del st.session_state[f"peso_{nome}"]
    st.rerun()

# ---------------------------------------------------------------- chiave API

st.header("Chiave API-Football")
st.markdown(f"Chiave salvata: **{cg.maschera_chiave(chiave_salvata)}**")
if os.environ.get("API_FOOTBALL_KEY"):
    st.info(
        "È impostata la variabile d'ambiente API_FOOTBALL_KEY: "
        "ha la precedenza sulla chiave salvata qui."
    )
with st.form("form_chiave", clear_on_submit=True):
    nuova = st.text_input("Nuova chiave", type="password", key="chiave_api_nuova")
    invia = st.form_submit_button("Salva chiave", key="salva_chiave_api")
if invia:
    if not nuova.strip():
        st.error("Inserisci la chiave API")
    else:
        with apri() as s:
            repo.scrivi_impostazione(s, "chiave_api", nuova.strip())
        del st.session_state["chiave_api_nuova"]  # la chiave non resta nel campo
        st.rerun()
