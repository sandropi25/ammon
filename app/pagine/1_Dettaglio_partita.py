"""Dettaglio partita: contesto, classifica dei candidati, quote, tipster, duelli e formazioni."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aggiorna  # noqa: E402

aggiorna.ricarica_se_cambiato(lambda: __import__("streamlit").cache_data.clear())

from datetime import datetime  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import cache_dati  # noqa: E402
import campo  # noqa: E402
import componenti  # noqa: E402
import componenti_giocate as cg  # noqa: E402
import stile  # noqa: E402
from auth import richiedi_password  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402
from ammonizioni.motore.classifica import converti_quota  # noqa: E402

st.set_page_config(page_title=f"Dettaglio partita · {stile.NOME_APP}", layout="wide")
richiedi_password()
stile.applica_stile()

st.title("Dettaglio partita")

partita_id = componenti.id_partita(st.query_params.get("partita"))
if st.query_params.get("partita") is None:
    st.info("Nessuna partita selezionata: scegline una dalla pagina Partite.")
    st.stop()

# le quote inserite restano nella sessione (non nel database), per partita
quote: dict[int, float] = st.session_state.setdefault(f"quote_{partita_id}", {})


def aggiorna_quota(giocatore_id: int) -> None:
    """Quota scritta nel riquadro "Scommetti": valida -> in sessione (barra e confronto col
    modello si aggiornano subito); vuota -> tolta; non valida -> messaggio."""
    testo = str(st.session_state.get(f"quota_{giocatore_id}", "")).strip()
    st.session_state.pop(f"errore_quota_{giocatore_id}", None)
    if not testo:
        quote.pop(giocatore_id, None)
        return
    try:
        quote[giocatore_id] = converti_quota(testo)
    except ValueError as errore:
        quote.pop(giocatore_id, None)
        st.session_state[f"errore_quota_{giocatore_id}"] = str(errore)


def apri_puntata(giocatore_id: int) -> None:
    """"L'ho giocata": apre la casella della puntata con la conferma."""
    st.session_state[f"apri_puntata_{giocatore_id}"] = True

pagina = None
if partita_id is not None:
    pagina = cache_dati.pagina_dettaglio(partita_id)

if pagina is None:
    st.error("Partita non trovata.")
    st.stop()

det = pagina.dettaglio
dati, partita = det.dati, det.partita
cambi, extra = pagina.cambi, pagina.extra
candidati = componenti.applica_quote(det.candidati, quote)

casa, trasf = dati.nomi_squadre.get(dati.casa_id, ""), dati.nomi_squadre.get(dati.trasferta_id, "")
# desktop: titolo e contesto a sinistra, campo a destra (~45%); telefono: campo sotto il titolo
sinistra, destra = st.columns([55, 45], gap="medium")
with sinistra:
    st.header(f"{casa} – {trasf}")
    giornata = f" · Giornata {partita.giornata}" if partita.giornata else ""
    st.caption(f"{componenti.data_italiana(partita.data_utc)}{giornata} · {componenti.etichetta_formazioni(partita.stato_formazioni)}")
if pagina.campo is not None and (pagina.campo.casa.titolari or pagina.campo.trasferta.titolari):
    with destra, st.container(key="campo_formazioni"):
        st.html(f"<style>{campo.campo_css(pagina.campo)}</style>")
        st.markdown(campo.campo_html(pagina.campo), unsafe_allow_html=True)
contesto = stile.scheda_contesto(componenti.righe_contesto(dati))
# il contesto accanto al campo su desktop, sotto il campo su telefono
nome_arbitro = dati.arbitro.nome if dati.arbitro and dati.arbitro.nome else None
with sinistra, st.container(key="solo_desktop_contesto"):
    st.markdown(contesto, unsafe_allow_html=True)
    stile.link_arbitro(partita.arbitro_id, nome_arbitro, "dettaglio_desktop")
with st.container(key="solo_telefono_contesto"):
    st.markdown(contesto, unsafe_allow_html=True)
    stile.link_arbitro(partita.arbitro_id, nome_arbitro, "dettaglio_telefono")

if cambi:
    st.subheader("Cambi rispetto alle formazioni probabili")
    st.markdown(stile.scheda_contesto(cambi), unsafe_allow_html=True)

st.subheader("Candidati all'ammonizione")
righe = componenti.righe_tabella(candidati, dati.nomi_squadre, det.tipster)
subentranti = componenti.applica_quote(det.subentranti, quote)
per_affidabilita = st.toggle(
    "Ordina per affidabilità",
    key="ordina_affidabilita",
    help="Predefinito: per probabilità. L'affidabilità dice quanto sono solidi i dati dietro "
    "la probabilità (0-100); non la cambia.",
)
solida = componenti.puntata_piu_solida(candidati + subentranti)
if solida is not None:
    st.markdown(
        stile.riquadro_puntata_solida(solida, dati.nomi_squadre.get(solida.squadra_id, "")),
        unsafe_allow_html=True,
    )
if not righe:
    st.info("Nessun candidato: mancano le formazioni e lo storico dei titolari.")
else:
    # barre di probabilità (anche su telefono); la tabella completa solo su schermi larghi
    st.markdown(
        "".join(
            stile.barra_probabilita(
                c, dati.nomi_squadre.get(c.squadra_id, ""), det.tipster.get(c.giocatore_id, [])
            )
            for c in componenti.ordina_candidati(candidati, per_affidabilita)
        ),
        unsafe_allow_html=True,
    )
    with st.container(key="solo_desktop_tabella_candidati"):
        with st.expander("Tabella completa"):
            tabella = pd.DataFrame(righe, columns=list(componenti.COLONNE_TABELLA))
            st.dataframe(
                tabella.style.map(componenti.colore_valore, subset=["Valore"]),
                hide_index=True,
                width="stretch",
            )

# probabili subentranti: tabella a parte sotto i titolari, ordinati per probabilità
if subentranti:
    st.subheader("Probabili subentranti")
    st.caption(
        "Panchinari che entrano almeno il 15% delle volte: probabilità ridotta dai minuti "
        "che giocano di solito. \"Sopra la media\" = gialli o falli per 90' sopra la media "
        "del ruolo (solo un'evidenza, non un filtro)."
    )
    st.markdown(
        "".join(
            stile.barra_probabilita(c, dati.nomi_squadre.get(c.squadra_id, ""))
            for c in componenti.ordina_candidati(subentranti, per_affidabilita)
        ),
        unsafe_allow_html=True,
    )
    with st.container(key="solo_desktop_tabella_subentranti"):
        with st.expander("Tabella dei subentranti"):
            st.dataframe(
                pd.DataFrame(
                    componenti.righe_subentranti(subentranti, dati.nomi_squadre),
                    columns=list(componenti.COLONNE_SUBENTRANTI),
                ),
                hide_index=True,
                width="stretch",
            )

if candidati:
    st.subheader("Duelli, storia e quote")

nomi = {c.giocatore_id: c.nome for c in candidati}

for c in candidati:
    info = extra[c.giocatore_id]
    squadra = dati.nomi_squadre.get(c.squadra_id, "")
    with st.expander(f"{c.nome} ({squadra}) · {componenti.percentuale(c.probabilita)}"):
        avv_nome = next((n for i, n in info["avversari"] if i == c.avversario_diretto_id), "n.d.")
        colonne = st.columns(2)
        colonne[0].markdown(f"**{c.nome}**")
        colonne[1].markdown(f"**{avv_nome}** (avversario diretto)")
        st.table(pd.DataFrame(componenti.righe_duello(info["stat"], info["stat_avv"])).set_index("Statistica")
                 .rename(columns={"Giocatore": c.nome, "Avversario": avv_nome}))
        st.caption(info["storia"])
        st.markdown(" · ".join(f"[{nome}]({url})" for nome, url in info["link"]))

        opzioni = [None] + [i for i, _ in info["avversari"]]
        nomi_avv = dict(info["avversari"])
        indice = opzioni.index(c.avversario_diretto_id) if c.avversario_diretto_id in opzioni else 0
        scelto = st.selectbox(
            "Avversario diretto",
            opzioni,
            index=indice,
            format_func=lambda i, n=nomi_avv: "(nessuno)" if i is None else n.get(i, str(i)),
            key=f"duello_{c.giocatore_id}",
        )
        if scelto is not None and scelto != c.avversario_diretto_id:
            with apri() as s:
                componenti.salva_duello(s, partita_id, c.giocatore_id, scelto)
            cache_dati.svuota()
            st.rerun()
        if scelto is None and c.giocatore_id in dati.duelli_manuali:
            with apri() as s:
                componenti.rimuovi_duello(s, partita_id, c.giocatore_id)
            cache_dati.svuota()
            del st.session_state[f"duello_{c.giocatore_id}"]  # torna l'avversario automatico
            st.rerun()

        # riquadro "Scommetti": quota del bookmaker contro il modello, poi "L'ho giocata"
        gid = c.giocatore_id
        with st.container(key=f"scommetti_{gid}"):
            st.markdown("**Scommetti**")
            st.text_input(
                "Quota del bookmaker (giocatore ammonito)", key=f"quota_{gid}",
                placeholder="es. 4,50", on_change=aggiorna_quota, args=(gid,),
            )
            if st.session_state.get(f"errore_quota_{gid}"):
                st.error(st.session_state[f"errore_quota_{gid}"])
            quota = quote.get(gid)
            if quota:
                st.markdown(
                    stile.riquadro_scommetti(cg.valuta_quota(c.probabilita, quota)),
                    unsafe_allow_html=True,
                )
            registrata = pagina.giocate.get(gid)
            if registrata is not None:
                st.success(cg.testo_giocata(*registrata))
            elif not quota:
                st.caption("Scrivi la quota per vedere se conviene e registrare la giocata.")
            elif st.session_state.get(f"apri_puntata_{gid}"):
                with st.form(f"form_puntata_{gid}"):
                    puntata = st.text_input("Puntata (€)", key=f"puntata_{gid}", placeholder="es. 10")
                    colonne_p = st.columns(2)
                    conferma = colonne_p[0].form_submit_button(
                        "Conferma", key=f"conferma_giocata_{gid}", type="primary"
                    )
                    annulla = colonne_p[1].form_submit_button("Annulla", key=f"annulla_giocata_{gid}")
                if annulla:
                    st.session_state.pop(f"apri_puntata_{gid}", None)
                    st.rerun()
                if conferma:
                    try:
                        with apri() as s:
                            cg.registra_scommessa(
                                s, partita_id, gid, quota, puntata,
                                datetime.now(componenti.ROMA).date(),
                            )
                    except ValueError as errore:
                        st.error(str(errore))
                    else:
                        st.session_state.pop(f"apri_puntata_{gid}", None)
                        cache_dati.svuota()
                        st.rerun()
            else:
                st.button(
                    "L'ho giocata", key=f"giocata_{gid}", on_click=apri_puntata, args=(gid,),
                )

        st.page_link(
            "pagine/2_Giocate.py",
            label="Registra con un'altra fonte (tipster, modello) →",
            query_params={"partita": partita_id, "giocatore": c.giocatore_id},
        )

if candidati:
    st.subheader("Segnalazione tipster")
    with st.form("form_tipster", clear_on_submit=True):
        nome_tipster = st.text_input("Tipster", key="tipster_nome")
        giocatore_tipster = st.selectbox(
            "Giocatore", list(nomi), format_func=lambda i: nomi[i], key="tipster_giocatore"
        )
        quota_tipster = st.text_input("Quota (facoltativa)", key="tipster_quota")
        invia_tipster = st.form_submit_button("Salva segnalazione", key="salva_tipster")
    if invia_tipster:
        try:
            with apri() as s:
                componenti.salva_segnalazione(
                    s, partita_id, giocatore_tipster, nome_tipster, quota_tipster
                )
        except ValueError as errore:
            st.error(str(errore))
        else:
            cache_dati.svuota()
            st.rerun()

