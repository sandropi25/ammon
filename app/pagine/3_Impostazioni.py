"""Impostazioni: derby e campi caldi (sola lettura, calcolati), pesi del modello e chiavi API."""
import os
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import componenti_giocate as cg  # noqa: E402
import stile  # noqa: E402
from auth import richiedi_password  # noqa: E402
from ammonizioni.db import repo  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402
from ammonizioni.motore.pesi import Pesi, carica_pesi, salva_pesi  # noqa: E402

st.set_page_config(page_title=f"Impostazioni · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

st.title("Impostazioni")

with apri() as s:
    pesi = carica_pesi(s)
    chiave_salvata = repo.leggi_impostazione(s, "chiave_api", None)
    chiave_football_data = repo.leggi_impostazione(s, "chiave_football_data", None)

rivalita = cache_dati.elenco_rivalita(datetime.now(timezone.utc))

schede = st.tabs(["Derby e campi caldi", "Pesi del modello", "Chiavi API"])

# ---------------------------------------------------------------- derby e campi caldi

with schede[0], st.container(key="riquadro_impostazioni_0"):
    st.caption(
        "Derby e campi caldi sono riconosciuti in automatico e contano nel punteggio "
        "dei giocatori e nelle partite calde: non c'è niente da inserire."
    )
    st.header("Derby e rivalità")
    if not rivalita.derby:
        st.caption("Nessun derby riconosciuto nei dati.")
    for campionato, testo in rivalita.derby:
        st.markdown(f"**{escape(testo)}** · {escape(campionato)}")

    st.header("Campi caldi")
    st.caption(
        "Squadre che in casa vedono almeno il 20% di cartellini in più della media del "
        "campionato (ultime 2 stagioni, almeno 15 partite in casa)."
    )
    if not rivalita.campi_caldi:
        st.caption("Nessun campo caldo calcolato.")
    for motivo in rivalita.campi_caldi:
        st.markdown(escape(motivo))


# ---------------------------------------------------------------- pesi

with schede[1], st.container(key="riquadro_impostazioni_1"):
    st.header("Pesi del modello")
    scalari, nomi_tuple = cg.campi_pesi()
    with st.form("form_pesi"):
        valori_scalari: dict[str, float] = {}
        for nome, tipo in scalari:
            corrente = getattr(pesi, nome)
            if tipo is int:
                valori_scalari[nome] = st.number_input(nome, value=int(corrente), min_value=0, step=1, key=f"peso_{nome}")
            else:
                passo = 0.01 if abs(corrente) < 10 else 1.0
                valori_scalari[nome] = st.number_input(
                    nome, value=float(corrente), min_value=0.0, step=passo, format="%g", key=f"peso_{nome}"
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
            cache_dati.svuota()
            st.rerun()
    if ripristina:
        with apri() as s:
            salva_pesi(s, Pesi())
        cache_dati.svuota()
        for nome, _ in scalari:
            del st.session_state[f"peso_{nome}"]
        for nome in nomi_tuple:
            del st.session_state[f"peso_{nome}"]
        st.rerun()


# ---------------------------------------------------------------- chiave API

with schede[2], st.container(key="riquadro_impostazioni_2"):
    st.header("Chiave football-data.org")
    st.caption("Serve per gli arbitri di Serie A e Liga (fonte ESPN predefinita).")
    st.markdown(f"Chiave salvata: **{cg.maschera_chiave(chiave_football_data)}**")
    if os.environ.get("FOOTBALL_DATA_KEY"):
        st.info(
            "È impostata la variabile d'ambiente FOOTBALL_DATA_KEY: "
            "ha la precedenza sulla chiave salvata qui."
        )
    with st.form("form_chiave_football_data", clear_on_submit=True):
        nuova_fd = st.text_input("Nuova chiave", type="password", key="chiave_football_data_nuova")
        invia_fd = st.form_submit_button("Salva chiave", key="salva_chiave_football_data")
    if invia_fd:
        if not nuova_fd.strip():
            st.error("Inserisci la chiave di football-data.org")
        else:
            with apri() as s:
                repo.scrivi_impostazione(s, "chiave_football_data", nuova_fd.strip())
            del st.session_state["chiave_football_data_nuova"]  # la chiave non resta nel campo
            st.rerun()

    st.header("Chiave API-Football (solo se usi API-Football, FONTE_DATI=api_football)")
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
