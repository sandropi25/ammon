"""Partite calde: le partite in programma della stagione che si prevedono piene di cartellini
(derby, campo caldo, precedenti, arbitro, squadre nervose), divise per giorno con l'orario
di Roma. In cima i prossimi 7 giorni, poi il resto della stagione."""
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

st.set_page_config(page_title=f"Partite calde · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

filtro = stile.selettore_campionato()
st.title("Partite calde")
st.caption(
    "Derby, campi caldi e partite dove i dati fanno prevedere tanti cartellini "
    "(gialli e rossi di entrambe le squadre)."
)

adesso = datetime.now(timezone.utc)
prossime, resto = cache_dati.partite_calde(adesso, componenti.campionati_del_filtro(filtro))


def mostra(righe, prefisso: str) -> None:
    for n, (titolo_giorno, del_giorno) in enumerate(componenti.raggruppa_per_giorno(righe, adesso)):
        st.subheader(titolo_giorno)
        with st.container(key=f"{prefisso}_{n}"):
            for p in del_giorno:
                with st.container(key=f"scheda_partita_{prefisso}_{p.id}"):
                    st.markdown(stile.scheda_partita(p), unsafe_allow_html=True)
                    stile.link_arbitro(p.arbitro_id, p.arbitro, f"{prefisso}_{p.id}")
                    st.page_link(
                        "pagine/1_Dettaglio_partita.py",
                        label="Apri dettaglio →",
                        query_params={"partita": p.id},
                    )


st.header("Prossimi 7 giorni")
if prossime:
    mostra(prossime, "calde7")
else:
    dove = "" if filtro == componenti.TUTTI else f" di {filtro}"
    st.info(f"Nessuna partita calda{dove} nei prossimi 7 giorni.")

if resto:
    st.header("Il resto della stagione")
    mostra(resto, "calderesto")
