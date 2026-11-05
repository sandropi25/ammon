"""Punto d'ingresso dell'app (anche su Streamlit Cloud): menu in alto come un sito web.

Le pagine restano file separati in pagine/ (non "pages/": con quella cartella Streamlit
userebbe il vecchio menu automatico e ignorerebbe st.navigation); la pagina iniziale è
pagine/0_Partite.py.
Gli indirizzi delle pagine non cambiano (es. /Dettaglio_partita?partita=123)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import stile  # noqa: E402

st.set_page_config(
    page_title=stile.NOME_APP, page_icon="🟨", layout="wide", initial_sidebar_state="collapsed"
)

pagine = [
    st.Page("pagine/0_Partite.py", title="Partite", icon="📅", default=True),
    st.Page("pagine/6_Partite_calde.py", title="Partite calde", icon="🔥"),
    st.Page("pagine/5_Calendario.py", title="Calendario", icon="🗓️"),
    st.Page("pagine/4_Cerca.py", title="Cerca", icon="🔎"),
    st.Page("pagine/1_Dettaglio_partita.py", title="Dettaglio partita", visibility="hidden"),
    st.Page("pagine/2_Giocate.py", title="Giocate", icon="🎯"),
    st.Page("pagine/3_Impostazioni.py", title="Impostazioni", icon="⚙️"),
]
st.navigation(pagine, position="top").run()
