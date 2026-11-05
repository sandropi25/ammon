"""Calendario: tutte le partite di una giornata del campionato scelto (Serie A predefinita),
con le frecce per cambiare giornata. Si apre sulla giornata in corso; le partite giocate
mostrano risultato, arbitro e cartellini totali, quelle da giocare arbitro e formazioni."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import componenti  # noqa: E402
import componenti_calendario as calendario  # noqa: E402
import stile  # noqa: E402
from ammonizioni.config import NOMI_CAMPIONATI  # noqa: E402
from auth import richiedi_password  # noqa: E402

st.set_page_config(page_title=f"Calendario · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

filtro = stile.selettore_campionato()
# il calendario ha le giornate di un solo campionato alla volta: "Tutti" mostra la Serie A
campionato = componenti.campionati_del_filtro(filtro)[0]
st.title("Calendario")
if filtro == componenti.TUTTI:
    st.caption("Il calendario si vede un campionato alla volta: scegli Serie A o Liga.")

cal = cache_dati.calendario(campionato)
if not cal.turni:
    st.info(f"Nessuna partita di {NOMI_CAMPIONATI[campionato]} nel calendario di questa stagione.")
    st.stop()

CHIAVE_TURNO = f"calendario_turno_{campionato}"
indice = cal.indice(st.session_state.get(CHIAVE_TURNO))
turno = cal.turni[indice]


def vai(chiave: int) -> None:
    st.session_state[CHIAVE_TURNO] = chiave


precedente, centro, successivo = st.columns([1, 4, 1], vertical_alignment="center")
with precedente:
    st.button(
        "◀", key="calendario_precedente", disabled=indice == 0, use_container_width=True,
        help="Giornata precedente" if cal.per_giornata else "Settimana precedente",
        on_click=vai, args=(cal.turni[max(indice - 1, 0)].chiave,),
    )
with successivo:
    st.button(
        "▶", key="calendario_successivo", disabled=indice == len(cal.turni) - 1,
        use_container_width=True,
        help="Giornata successiva" if cal.per_giornata else "Settimana successiva",
        on_click=vai, args=(cal.turni[min(indice + 1, len(cal.turni) - 1)].chiave,),
    )

adesso = datetime.now(timezone.utc)
partite = cache_dati.righe_turno(turno)
with centro:
    st.markdown(
        stile.titolo_turno(turno.etichetta, calendario.sottotitolo(partite)),
        unsafe_allow_html=True,
    )

if indice != cal.in_corso:
    st.button(
        "Vai alla giornata in corso" if cal.per_giornata else "Vai alla settimana in corso",
        key="calendario_in_corso", on_click=vai, args=(cal.turni[cal.in_corso].chiave,),
    )

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
