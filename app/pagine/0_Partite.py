"""Pagina iniziale: prossime partite del campionato scelto (Serie A predefinita, Liga, Tutti),
come schede divise per giorno; ogni scheda porta al dettaglio."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import componenti  # noqa: E402
import stile  # noqa: E402
from auth import richiedi_password  # noqa: E402

st.set_page_config(page_title=f"Partite · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

filtro = stile.selettore_campionato()
st.title("Prossime partite")

adesso = datetime.now(timezone.utc)
_, completo, partite = cache_dati.pagina_partite(
    adesso, componenti.campionati_del_filtro(filtro)
)

if not completo:
    st.warning("Dati parziali: l'ultimo aggiornamento notturno non è stato completato.")

if not partite:
    dove = "" if filtro == componenti.TUTTI else f" di {filtro}"
    st.info(f"Nessuna partita{dove} nei prossimi 7 giorni.")

for n, (titolo_giorno, del_giorno) in enumerate(componenti.raggruppa_per_giorno(partite, adesso)):
    st.subheader(titolo_giorno)
    with st.container(key=f"giorno_{n}"):
        for p in del_giorno:
            with st.container(key=f"scheda_partita_{p.id}"):
                st.markdown(stile.scheda_partita(p), unsafe_allow_html=True)
                st.page_link(
                    "pagine/1_Dettaglio_partita.py",
                    label="Apri dettaglio →",
                    query_params={"partita": p.id},
                )
