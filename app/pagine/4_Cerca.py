"""Cerca: un giocatore o una squadra (senza accenti né maiuscole). Il giocatore ha la sua
scheda (prossima partita, statistiche per stagione, ultime partite); la squadra mostra le
partite in programma dei prossimi 30 giorni."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import componenti  # noqa: E402
import componenti_cerca as cerca  # noqa: E402
import stile  # noqa: E402
from auth import richiedi_password  # noqa: E402

PAGINA = "pagine/4_Cerca.py"

st.set_page_config(page_title=f"Cerca · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

st.title("Cerca")
testo = st.text_input(
    "Cerca",
    key="cerca_testo",
    placeholder="Cerca un giocatore o una squadra…",
    label_visibility="collapsed",
)
filtro = stile.selettore_campionato()
adesso = datetime.now(timezone.utc)


def torna_alla_ricerca() -> None:
    st.page_link(PAGINA, label="← Nuova ricerca")


def mostra_giocatore(giocatore_id: int) -> None:
    torna_alla_ricerca()
    scheda = cache_dati.scheda_giocatore(giocatore_id, adesso)
    if scheda is None:
        st.error("Giocatore non trovato.")
        return
    ruolo = stile.RUOLI.get(scheda.ruolo, "")
    sotto = " · ".join(x for x in (scheda.squadra, ruolo) if x)
    if scheda.diffidato:
        stato = stile.badge(f"🟨 Diffidato · {scheda.gialli_campionato} gialli in campionato", "giallo")
    else:
        stato = stile.badge(f"Non diffidato · {scheda.gialli_campionato} gialli in campionato", "neutro")
    st.markdown(stile.testa_giocatore(scheda.nome, sotto, [stato]), unsafe_allow_html=True)

    st.subheader("Prossima partita")
    p = scheda.prossima
    if p is None:
        st.info("Nessuna prossima partita in calendario.")
    else:
        casa, trasf = (scheda.squadra, p.avversario) if p.in_casa else (p.avversario, scheda.squadra)
        st.markdown(f"**{casa} – {trasf}**  \n{p.quando}")
        if p.candidato is not None:
            st.markdown(stile.barra_probabilita(p.candidato, scheda.squadra), unsafe_allow_html=True)
        else:
            st.info("Non è tra i candidati: formazioni non ancora note o non è tra i titolari.")
        if p.arbitro is None:
            st.caption("Arbitro non ancora designato.")
        else:
            presenze, gialli = p.con_arbitro
            con = (
                f"{presenze} presenze, {gialli} gialli" if presenze else "nessun precedente nei dati"
            )
            st.caption(f"Arbitro: {p.arbitro} · con lui: {con}")
        st.caption(p.storia)
        if p.derby:
            st.caption(p.derby)
        st.page_link(
            "pagine/1_Dettaglio_partita.py", label="Apri dettaglio partita →",
            query_params={"partita": p.partita_id},
        )

    st.subheader("Statistiche per stagione")
    if not scheda.stagioni:
        st.info("Nessuna presenza nei dati.")
    else:
        with st.container(key="solo_desktop_stagioni"):
            st.markdown(
                stile.tabella(cerca.COLONNE_STAGIONI, [cerca.celle_stagione(r) for r in scheda.stagioni]),
                unsafe_allow_html=True,
            )
        with st.container(key="solo_telefono_stagioni"):
            st.markdown(
                stile.griglia([
                    stile.tessera(
                        f"{r.stagione} · {r.competizione}",
                        f"{r.presenze} presenze · {r.minuti} minuti",
                        list(zip(cerca.COLONNE_STAGIONI[4:], cerca.celle_stagione(r)[4:])),
                    )
                    for r in scheda.stagioni
                ]),
                unsafe_allow_html=True,
            )
        st.caption("Presenze = partite con almeno un minuto; i gialli dalla panchina sono inclusi.")

    st.subheader("Ultime partite")
    if not scheda.ultime:
        st.info("Nessuna partita recente nei dati.")
    else:
        st.markdown(
            stile.tabella(cerca.COLONNE_ULTIME, [cerca.celle_ultima(u) for u in scheda.ultime]),
            unsafe_allow_html=True,
        )


def mostra_squadra(squadra_id: int) -> None:
    torna_alla_ricerca()
    nome = next((q.nome for q in cache_dati.indice_ricerca().squadre if q.id == squadra_id), None)
    if nome is None:
        st.error("Squadra non trovata.")
        return
    st.header(nome)
    partite = cache_dati.partite_squadra(squadra_id, adesso)
    if not partite:
        st.info(f"Nessuna partita in programma nei prossimi {cerca.GIORNI_SQUADRA} giorni.")
    st.caption(f"Partite in programma nei prossimi {cerca.GIORNI_SQUADRA} giorni")
    for n, (titolo_giorno, del_giorno) in enumerate(componenti.raggruppa_per_giorno(partite, adesso)):
        st.subheader(titolo_giorno)
        with st.container(key=f"giorno_{n}"):
            for p in del_giorno:
                with st.container(key=f"scheda_partita_{p.id}"):
                    st.markdown(stile.scheda_partita(p), unsafe_allow_html=True)
                    st.page_link(
                        "pagine/1_Dettaglio_partita.py", label="Apri dettaglio →",
                        query_params={"partita": p.id},
                    )


def mostra_risultati() -> None:
    if len(cerca.normalizza(testo)) < cerca.MIN_CARATTERI:
        st.info("Scrivi almeno due lettere: cerca per nome, anche senza accenti (es. «calhanoglu»).")
        return
    indice = cache_dati.indice_ricerca()
    giocatori, totale = cerca.cerca_giocatori(indice, testo)
    campionati = componenti.campionati_del_filtro(filtro)
    squadre, nascoste = cerca.cerca_squadre(indice, testo, campionati, tutti=filtro == componenti.TUTTI)
    if not giocatori and not squadre:
        st.info("Nessun risultato.")

    if giocatori:
        st.subheader("Giocatori")
        if totale > len(giocatori):
            st.caption(f"Primi {len(giocatori)} di {totale}: scrivi di più per restringere.")
        with st.container(key="giorno_giocatori"):
            for g in giocatori:
                sotto = " · ".join(x for x in (g.squadra, stile.RUOLI.get(g.ruolo, "")) if x)
                with st.container(key=f"scheda_partita_giocatore_{g.id}"):
                    st.markdown(stile.risultato_ricerca(g.nome, sotto), unsafe_allow_html=True)
                    st.page_link(PAGINA, label="Apri scheda →", query_params={"giocatore": g.id})

    if squadre:
        st.subheader("Squadre")
        with st.container(key="giorno_squadre"):
            for q in squadre:
                with st.container(key=f"scheda_partita_squadra_{q.id}"):
                    st.markdown(stile.risultato_ricerca(q.nome, "Squadra"), unsafe_allow_html=True)
                    st.page_link(PAGINA, label="Partite in programma →", query_params={"squadra": q.id})
    if nascoste:
        st.caption(
            f"{nascoste} squadre di altri campionati corrispondono: scegli «Liga» o «Tutti» per vederle."
        )


giocatore_id = componenti.id_partita(st.query_params.get("giocatore"))
squadra_id = componenti.id_partita(st.query_params.get("squadra"))
if giocatore_id is not None:
    mostra_giocatore(giocatore_id)
elif squadra_id is not None:
    mostra_squadra(squadra_id)
else:
    mostra_risultati()
