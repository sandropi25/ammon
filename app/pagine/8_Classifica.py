"""Classifica: la classifica del campionato scelto (Serie A predefinita, "Tutti" mostra
Serie A e Liga una sotto l'altra), calcolata dai risultati nel database. Forma delle ultime
5, zone europee e retrocessione, gialli e rossi a partita (anche dalla panchina). Un clic
su una squadra apre la sua pagina in Cerca."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import componenti  # noqa: E402
import componenti_classifica as cc  # noqa: E402
import stile  # noqa: E402
from auth import richiedi_password  # noqa: E402

st.set_page_config(page_title=f"Classifica · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

filtro = stile.selettore_campionato()
st.title("Classifica")
st.caption(
    "Calcolata dai risultati delle partite finite della stagione. 🟨/P e 🟥/P: gialli e rossi "
    "a partita della squadra, anche quelli presi dalla panchina. Tocca una squadra per aprirla."
)

for classifica in cache_dati.classifiche(componenti.campionati_del_filtro(filtro)):
    if filtro == componenti.TUTTI:
        st.header(classifica.nome)
    if not classifica.righe:
        st.info(f"Nessuna partita di {classifica.nome} nei dati di questa stagione.")
        continue
    with st.container(key=f"tabella_cl_{classifica.campionato}"):
        st.markdown(stile.testa_classifica(), unsafe_allow_html=True)
        for r in classifica.righe:
            with st.container(key=f"riga_cl_{classifica.campionato}_{r.squadra_id}"):
                st.markdown(stile.riga_classifica(r), unsafe_allow_html=True)
                st.page_link("pagine/4_Cerca.py", label=r.nome, query_params={"squadra": r.squadra_id})
    st.markdown(stile.legenda_zone(classifica.zone), unsafe_allow_html=True)

st.caption(cc.NOTA_CRITERI)
