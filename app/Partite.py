"""Pagina iniziale: prossime partite di Serie A."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

import componenti  # noqa: E402
from auth import richiedi_password  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402

st.set_page_config(page_title="Ammonizioni Serie A", layout="wide")
richiedi_password()

st.title("Prossime partite")

with apri() as s:
    testo_agg, completo = componenti.stato_aggiornamento(s)
    partite = componenti.prossime_partite(s, datetime.now(timezone.utc))

st.caption(testo_agg)
if not completo:
    st.warning("Dati parziali: l'ultimo aggiornamento notturno non è stato completato.")

if not partite:
    st.info("Nessuna partita di Serie A nei prossimi 7 giorni.")

for p in partite:
    with st.container(border=True):
        colonne = st.columns([5, 2])
        with colonne[0]:
            giornata = f" · Giornata {p.giornata}" if p.giornata else ""
            st.markdown(f"**{p.casa} – {p.trasferta}**{giornata} · {p.quando}")
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
