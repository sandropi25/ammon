"""Pagina iniziale: prossime partite dei campionati (Serie A predefinita, Liga, Tutti)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

import componenti  # noqa: E402
from auth import richiedi_password  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402

st.set_page_config(page_title="Ammonizioni Serie A e Liga", layout="wide")
richiedi_password()

st.title("Prossime partite")

filtro = st.radio(
    "Campionato",
    componenti.FILTRO_CAMPIONATI,
    index=componenti.FILTRO_CAMPIONATI.index(componenti.FILTRO_PREDEFINITO),
    horizontal=True,
    key="filtro_partite",
)

with apri() as s:
    testo_agg, completo = componenti.stato_aggiornamento(s)
    partite = componenti.prossime_partite(
        s, datetime.now(timezone.utc), campionati=componenti.campionati_del_filtro(filtro)
    )

st.caption(testo_agg)
if not completo:
    st.warning("Dati parziali: l'ultimo aggiornamento notturno non è stato completato.")

if not partite:
    dove = "" if filtro == componenti.TUTTI else f" di {filtro}"
    st.info(f"Nessuna partita{dove} nei prossimi 7 giorni.")

for p in partite:
    with st.container(border=True):
        colonne = st.columns([5, 2])
        with colonne[0]:
            giornata = f" · Giornata {p.giornata}" if p.giornata else ""
            campionato = f" · {p.campionato}" if p.campionato else ""
            st.markdown(f"**{p.casa} – {p.trasferta}**{campionato}{giornata} · {p.quando}")
            arbitro = p.arbitro or "da designare"
            st.caption(f"Arbitro: {arbitro} · Formazioni: {p.formazioni}")
            if p.calda:
                st.markdown(":red[**Partita calda**]")
        with colonne[1]:
            st.page_link(
                "pages/1_Dettaglio_partita.py",
                label="Apri dettaglio",
                query_params={"partita": p.id},
            )
