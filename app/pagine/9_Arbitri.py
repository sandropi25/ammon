"""Arbitri: l'elenco degli arbitri del campionato scelto (Serie A predefinita, "Tutti" per
entrambi) con le medie di gialli, rossi e falli, ordinabile; un clic apre la scheda
dell'arbitro (/Arbitri?arbitro=<id>) con il totale in carriera (dal 2023-24), la divisione per
campionato e stagione, le ultime 10 partite e la prossima partita designata."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import componenti  # noqa: E402
import componenti_arbitri as ca  # noqa: E402
import stile  # noqa: E402
from auth import richiedi_password  # noqa: E402

PAGINA = stile.PAGINA_ARBITRI

st.set_page_config(page_title=f"Arbitri · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

filtro = stile.selettore_campionato()
adesso = datetime.now(timezone.utc)


def mostra_elenco() -> None:
    campionati = componenti.campionati_del_filtro(filtro)
    elenco = cache_dati.elenco_arbitri(campionati)
    st.title("Arbitri")
    st.caption(ca.NOTA_CARRIERA + " " + ca.NOTA_TOTALI)
    if not elenco.righe:
        st.info("Nessun arbitro con i cartellini noti per questo campionato.")
        return
    criterio = st.selectbox("Ordina per", list(ca.CRITERI), key="arbitri_criterio")
    if elenco.media_gialli_lega is not None:
        st.caption(
            f"Media del campionato: {ca.numero(elenco.media_gialli_lega)} gialli a partita. "
            "Tocca un arbitro per la sua scheda."
        )
    righe = ca.ordina(elenco.righe, criterio)
    with st.container(key="tabella_cl_arbitri"):
        st.markdown(stile.testa_arbitri(), unsafe_allow_html=True)
        for posizione, r in enumerate(righe, start=1):
            with st.container(key=f"riga_cl_arbitro_{r.id}"):
                st.markdown(
                    stile.riga_arbitro(posizione, r, len(campionati) > 1), unsafe_allow_html=True
                )
                st.page_link(PAGINA, label=r.nome, query_params={"arbitro": r.id})


def mostra_scheda(arbitro_id: int) -> None:
    st.page_link(PAGINA, label="← Tutti gli arbitri")
    scheda = cache_dati.scheda_arbitro(arbitro_id, adesso)
    if scheda is None:
        st.error("Arbitro non trovato.")
        return
    t = scheda.totale
    quante = "1 partita" if t.partite == 1 else f"{t.partite} partite"
    badges = [stile.badge(nome, "neutro") for nome, _ in scheda.per_campionato]
    st.markdown(
        stile.testa_giocatore(scheda.nome, f"Arbitro · {quante} con i cartellini noti", badges),
        unsafe_allow_html=True,
    )
    st.caption(ca.NOTA_CARRIERA + " " + ca.NOTA_TOTALI)
    if scheda.senza_cartellini:
        st.caption(
            f"{scheda.senza_cartellini} partite arbitrate senza i cartellini nei dati: "
            "non contano nelle medie."
        )

    st.subheader("In carriera (dal 2023-24)")
    if not t.partite:
        st.info("Nessuna partita con i cartellini noti.")
    else:
        pezzi = [stile.tessera_statistiche("Totale", "Dal 2023-24", t)]
        if len(scheda.per_campionato) > 1:
            pezzi += [
                stile.tessera_statistiche(nome, "Dal 2023-24", st_c)
                for nome, st_c in scheda.per_campionato
            ]
        st.markdown(stile.griglia(pezzi), unsafe_allow_html=True)

    if scheda.per_stagione:
        st.subheader("Per stagione")
        with st.container(key="solo_desktop_stagioni_arbitro"):
            st.markdown(
                stile.tabella(
                    stile.COLONNE_ARBITRO_STAGIONI,
                    [stile.celle_stagione_arbitro(*riga) for riga in scheda.per_stagione],
                ),
                unsafe_allow_html=True,
            )
        with st.container(key="solo_telefono_stagioni_arbitro"):
            st.markdown(
                stile.griglia([
                    stile.tessera_statistiche(f"{camp} · {stagione}", "", st_s)
                    for camp, stagione, st_s in scheda.per_stagione
                ]),
                unsafe_allow_html=True,
            )

    st.subheader("Ultime partite")
    if not scheda.ultime:
        st.info("Nessuna partita arbitrata nei dati.")
    else:
        st.markdown(
            '<div class="cr-ar-lista">' + "".join(stile.partita_arbitrata(p) for p in scheda.ultime)
            + "</div>",
            unsafe_allow_html=True,
        )

    st.subheader("Prossima partita designata")
    pr = scheda.prossima
    if pr is None:
        st.info("Nessuna prossima partita designata nei dati.")
    else:
        st.markdown(
            '<div class="cr-ar-lista">' + stile.prossima_arbitro(pr) + "</div>",
            unsafe_allow_html=True,
        )
        st.page_link(
            "pagine/1_Dettaglio_partita.py", label="Apri dettaglio partita →",
            query_params={"partita": pr.id},
        )
        st.caption("Con le due squadre della partita (partite già arbitrate da lui):")
        st.markdown(
            stile.griglia([stile.con_squadra_arbitro(c) for c in pr.con_squadre]),
            unsafe_allow_html=True,
        )


arbitro_scelto = ca.id_arbitro(st.query_params.get("arbitro"))
if arbitro_scelto is None:
    mostra_elenco()
else:
    st.title("Arbitri")
    mostra_scheda(arbitro_scelto)
