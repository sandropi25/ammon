"""Giocate: registro delle giocate, nuovo inserimento e statistiche per fonte."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import componenti  # noqa: E402
import componenti_giocate as cg  # noqa: E402
from auth import richiedi_password  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402

st.set_page_config(page_title="Giocate", layout="wide")
richiedi_password()

st.title("Giocate")

# la pagina Dettaglio partita porta qui con ?partita=...&giocatore=...
partita_richiesta = componenti.id_partita(st.query_params.get("partita"))
giocatore_richiesto = componenti.id_partita(st.query_params.get("giocatore"))

with apri() as s:
    partite = cg.partite_selezionabili(s, datetime.now(timezone.utc), includi=partita_richiesta)
    registro = cg.righe_registro(s)
    statistiche = cg.righe_statistiche(s)

if st.session_state.pop("giocata_registrata", False):
    st.success("Giocata registrata")

st.subheader("Nuova giocata")
if not partite:
    st.info("Nessuna partita di Serie A negli ultimi e nei prossimi 7 giorni.")
else:
    nomi_partite = dict(partite)
    if partita_richiesta in nomi_partite:
        st.session_state.setdefault("giocata_partita", partita_richiesta)
    partita_id = st.selectbox(
        "Partita", list(nomi_partite), format_func=lambda i: nomi_partite[i], key="giocata_partita"
    )
    with apri() as s:
        giocatori = cg.giocatori_partita(s, partita_id)
    nomi_giocatori = dict(giocatori)
    if st.session_state.get("giocata_giocatore") not in nomi_giocatori:
        st.session_state.pop("giocata_giocatore", None)  # arriva da un'altra partita
        if giocatore_richiesto in nomi_giocatori and partita_id == partita_richiesta:
            st.session_state["giocata_giocatore"] = giocatore_richiesto
    giocatore_id = st.selectbox(
        "Giocatore",
        list(nomi_giocatori),
        format_func=lambda i: nomi_giocatori[i],
        key="giocata_giocatore",
    )
    giorno = st.date_input(
        "Data", value=datetime.now(componenti.ROMA).date(), format="DD/MM/YYYY", key="giocata_data"
    )
    colonne = st.columns(2)
    scelta_fonte = colonne[0].selectbox("Fonte", cg.FONTI, key="giocata_fonte")
    tipster = colonne[1].text_input(
        "Nome del tipster (se la fonte è tipster)", key="giocata_tipster"
    )
    colonne = st.columns(2)
    quota = colonne[0].text_input("Quota", key="giocata_quota", placeholder="es. 2,10")
    puntata = colonne[1].text_input("Puntata (€)", key="giocata_puntata", placeholder="es. 10,00")
    if st.button("Registra giocata", key="salva_giocata"):
        try:
            with apri() as s:
                cg.registra_giocata(
                    s, giorno, partita_id, giocatore_id, scelta_fonte, tipster, quota, puntata
                )
        except ValueError as errore:
            st.error(str(errore))
        else:
            st.session_state["giocata_registrata"] = True
            for chiave in ("giocata_quota", "giocata_puntata"):
                del st.session_state[chiave]
            st.rerun()

st.subheader("Registro")
if not registro:
    st.info("Nessuna giocata registrata.")
else:
    st.dataframe(
        pd.DataFrame(registro, columns=list(cg.COLONNE_REGISTRO)), hide_index=True, width="stretch"
    )

st.subheader("Statistiche per fonte")
if not statistiche:
    st.info("Nessuna giocata conclusa: le statistiche compaiono dopo i primi esiti.")
else:
    st.dataframe(
        pd.DataFrame(statistiche, columns=list(cg.COLONNE_STATISTICHE)),
        hide_index=True,
        width="stretch",
    )
