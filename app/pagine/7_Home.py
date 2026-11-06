"""Home (pagina iniziale): riquadri della giornata (partite di oggi e domani, la più calda,
il giocatore più a rischio, le giocate), classifica degli ammoniti della stagione, grafici
e profili dei giocatori (ESPN + Wikipedia). Vale il campionato scelto nel menu in alto."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import componenti  # noqa: E402
import componenti_giocate  # noqa: E402
import componenti_home as home  # noqa: E402
import grafici  # noqa: E402
import stile  # noqa: E402
from auth import richiedi_password  # noqa: E402

st.set_page_config(page_title=f"Home · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

PAGINA_CERCA = "pagine/4_Cerca.py"
PAGINA_DETTAGLIO = "pagine/1_Dettaglio_partita.py"
CHIAVE_VAI = "home_vai_giocatore"
CHIAVE_TABELLA = "home_tabella_n"

# un clic su una riga della classifica apre la scheda del giocatore (pagina Cerca)
vai = st.session_state.pop(CHIAVE_VAI, None)
if vai is not None:
    st.switch_page(PAGINA_CERCA, query_params={"giocatore": vai})

filtro = stile.selettore_campionato()
campionati = componenti.campionati_del_filtro(filtro)
tema = stile.tema_corrente()
adesso = datetime.now(timezone.utc)
oggi = adesso.astimezone(componenti.ROMA).date()
st.title("Home")
st.caption("La giornata di " + ("Serie A e Liga" if filtro == componenti.TUTTI else filtro))

# ---------------------------------------------------------------- riquadri

_, completo, prossime = cache_dati.pagina_partite(adesso, campionati)
if not completo:
    st.warning("Dati parziali: l'ultimo aggiornamento notturno non è stato completato.")
vicine = home.oggi_e_domani(prossime, adesso)
calde, _ = cache_dati.partite_calde(adesso, campionati)
calda = home.piu_calda(calde)
rischio = cache_dati.piu_a_rischio([r.id for r in prossime]) if prossime else None
giocate = cache_dati.riepilogo_giocate(campionati)


def _quando(r) -> str:
    giorno = r.data_utc.astimezone(componenti.ROMA).date()
    return ("Oggi" if giorno == oggi else "Domani") + f" {r.ora}"


with st.container(key="riquadri_home"):
    with st.container(key="riquadro_home_oggi"):
        if vicine:
            titolo = "1 partita" if len(vicine) == 1 else f"{len(vicine)} partite"
            righe = [f"{_quando(r)} · {r.casa} – {r.trasferta}" for r in vicine[:4]]
            if len(vicine) > 4:
                righe.append(f"e altre {len(vicine) - 4}")
            st.markdown(stile.riquadro_home("Oggi e domani", titolo, righe=righe), unsafe_allow_html=True)
        else:
            st.markdown(
                stile.riquadro_home("Oggi e domani", "Nessuna partita", "Si torna in campo nei prossimi giorni"),
                unsafe_allow_html=True,
            )
        st.page_link("pagine/0_Partite.py", label="Tutte le prossime partite →")

    with st.container(key="riquadro_home_calda"):
        if calda is not None:
            attesi = (
                f"🟨 {componenti.numero_it(calda.attesi)} cartellini attesi"
                if calda.attesi is not None else "Partita calda"
            )
            st.markdown(stile.riquadro_home(
                "Partita più calda", f"{calda.casa} – {calda.trasferta}",
                f"{calda.quando} · {attesi}", righe=list(calda.motivi[:2]),
                badges=[stile.badge("🔥 Calda", "rosso")],
            ), unsafe_allow_html=True)
            st.page_link(PAGINA_DETTAGLIO, label="Apri la partita →", query_params={"partita": calda.id})
        else:
            st.markdown(stile.riquadro_home(
                "Partita più calda", "Nessuna in vista", "Nei prossimi 7 giorni"
            ), unsafe_allow_html=True)

    with st.container(key="riquadro_home_rischio"):
        if rischio is not None:
            st.markdown(stile.riquadro_home(
                "Più a rischio giallo", rischio.nome, f"{rischio.squadra} · {rischio.partita}",
                badges=[stile.badge(f"🟨 {componenti.percentuale(rischio.probabilita)}", "giallo")],
            ), unsafe_allow_html=True)
            st.page_link(PAGINA_DETTAGLIO, label="Apri la partita →", query_params={"partita": rischio.partita_id})
        else:
            st.markdown(stile.riquadro_home(
                "Più a rischio giallo", "Nessun candidato", "Servono partite in programma"
            ), unsafe_allow_html=True)

    with st.container(key="riquadro_home_giocate"):
        if giocate.rendimento is not None:
            titolo = f"Rendimento {componenti.valore_testo(giocate.rendimento)}"
            sotto = (
                f"{giocate.vinte} vinte su {giocate.chiuse} · "
                f"profitto {componenti_giocate.euro(giocate.profitto)}"
            )
        else:
            titolo, sotto = "Nessuna giocata chiusa", "Registra le giocate per vedere il rendimento"
        righe = [f"{g['Data'][:5]} · {g['Giocatore']} · {g['Esito']}" for g in giocate.ultime]
        st.markdown(stile.riquadro_home("Le tue giocate", titolo, sotto, righe=righe), unsafe_allow_html=True)
        st.page_link("pagine/2_Giocate.py", label="Registro delle giocate →")

# ---------------------------------------------------------------- classifica

stats = cache_dati.statistiche_stagione(campionati)
st.subheader("Classifica degli ammoniti")
if not stats.classifica:
    st.info("Nessuna presenza registrata in questa stagione per il campionato scelto.")
else:
    cerca, ordina = st.columns([3, 2])
    with cerca:
        testo = st.text_input(
            "Cerca nella classifica", key="home_cerca", placeholder="Giocatore o squadra…",
            label_visibility="collapsed",
        )
    with ordina:
        ordine = st.selectbox(
            "Ordina per", list(home.ORDINAMENTI), key="home_ordine", label_visibility="collapsed",
        )
    righe = home.filtra_e_ordina(stats.classifica, testo, ordine)
    ids = tuple(r.giocatore_id for r in righe)
    n = st.session_state.setdefault(CHIAVE_TABELLA, 0)
    chiave = f"home_classifica_{n}"

    def _scelta(chiave: str = chiave, ids: tuple[int, ...] = ids) -> None:
        stato = st.session_state.get(chiave)
        scelte = list(getattr(getattr(stato, "selection", None), "rows", None) or [])
        if scelte and scelte[0] < len(ids):
            st.session_state[CHIAVE_VAI] = ids[scelte[0]]
            # tabella nuova al ritorno: la selezione vecchia non riapre la scheda
            st.session_state[CHIAVE_TABELLA] = st.session_state.get(CHIAVE_TABELLA, 0) + 1

    if righe:
        st.dataframe(
            home.righe_tabella(righe), hide_index=True, key=chiave, height=420,
            on_select=_scelta, selection_mode="single-row",
            column_config={
                "#": st.column_config.NumberColumn(width="small"),
                "Gialli 90'": st.column_config.NumberColumn(format="%.2f"),
                "Falli 90'": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.caption(
            "Tocca una riga per aprire la scheda del giocatore. Contano tutti i cartellini, "
            "anche quelli presi dalla panchina; i valori per 90' usano i minuti giocati."
        )
    else:
        st.info("Nessun giocatore corrisponde alla ricerca.")

    # ------------------------------------------------------------ grafici

    st.subheader("Grafici")
    primi, ritardo, giornate, squadre = st.tabs(
        ["Più ammoniti", "Falli e gialli", "Per giornata", "Per squadra"]
    )
    with primi:
        dati = home.dati_primi(stats.classifica)
        if dati:
            st.altair_chart(grafici.barre_primi(dati, tema), theme=None, width="stretch")
        else:
            st.info("Ancora nessun ammonito in questa stagione.")
    with ritardo:
        dati = home.dati_dispersione(stats.classifica)
        if dati:
            st.altair_chart(grafici.dispersione(dati, tema), theme=None, width="stretch")
            nomi = [d["Giocatore"] for d in dati if d["Gruppo"] == "In ritardo"]
            st.caption(
                "In rosso chi fa molti falli ma prende pochi gialli rispetto alla media: "
                "il giallo potrebbe essere in ritardo. Solo chi ha giocato almeno "
                f"{home.MINUTI_DISPERSIONE} minuti."
                + (f" In ritardo: {', '.join(nomi[:8])}." if nomi else "")
            )
        else:
            st.info(f"Servono giocatori con almeno {home.MINUTI_DISPERSIONE} minuti.")
    with giornate:
        if stats.per_giornata:
            st.altair_chart(grafici.per_giornata(stats.per_giornata, tema), theme=None, width="stretch")
        else:
            st.info("Nessuna giornata giocata con il numero di giornata.")
    with squadre:
        if stats.per_squadra:
            st.altair_chart(grafici.per_squadra(stats.per_squadra, tema), theme=None, width="stretch")
        else:
            st.info("Nessuna partita giocata in questa stagione.")

    # ------------------------------------------------------------ biografie

    bio = cache_dati.biografie(stats.classifica, oggi)
    if bio:
        st.subheader("Profili dei più ammoniti")
        with st.container(key="bio_home"):
            for b in bio:
                with st.container(key=f"bio_{b.giocatore_id}"):
                    st.markdown(stile.scheda_bio(b), unsafe_allow_html=True)
                    st.page_link(
                        PAGINA_CERCA, label="Scheda del giocatore →",
                        query_params={"giocatore": b.giocatore_id},
                    )
