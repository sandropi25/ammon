"""Dettaglio partita: contesto, classifica dei candidati, quote, tipster, duelli e formazioni."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import componenti  # noqa: E402
from auth import richiedi_password  # noqa: E402
from ammonizioni.caricamento.formazioni import salva_probabili  # noqa: E402
from ammonizioni.db.modelli import Giocatore  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402
from ammonizioni.motore.classifica import converti_quota  # noqa: E402

st.set_page_config(page_title="Dettaglio partita", layout="wide")
richiedi_password()

st.title("Dettaglio partita")

partita_id = componenti.id_partita(st.query_params.get("partita"))
if st.query_params.get("partita") is None:
    st.info("Nessuna partita selezionata: scegline una dalla pagina Partite.")
    st.stop()

# le quote inserite restano nella sessione (non nel database), per partita
quote: dict[int, float] = st.session_state.setdefault(f"quote_{partita_id}", {})

with apri() as s:
    det = componenti.carica_dettaglio(s, partita_id, quote) if partita_id is not None else None
    if det is not None:
        dati, partita = det.dati, det.partita
        cambi = componenti.righe_cambi(s, det)
        extra = {}
        for c in det.candidati:
            avv_id = c.avversario_diretto_id
            sq_avv = dati.trasferta_id if c.squadra_id == dati.casa_id else dati.casa_id
            sofascore = s.get(Giocatore, c.giocatore_id)
            extra[c.giocatore_id] = {
                "stat": componenti.statistiche_90(s, c.giocatore_id, dati.stagione, dati.data),
                "stat_avv": componenti.statistiche_90(s, avv_id, dati.stagione, dati.data)
                if avv_id else {"minuti": 0},
                "storia": componenti.testo_storia(
                    *componenti.storia_contro(s, c.giocatore_id, sq_avv, dati.data),
                    dati.nomi_squadre.get(sq_avv, ""),
                ),
                "link": componenti.link_sofascore(sofascore),
                "avversari": componenti.avversari_possibili(dati, c),
            }
        rosa = {}
        if partita.stato_formazioni == "probabili":
            for sq in (dati.casa_id, dati.trasferta_id):
                correnti = [t.giocatore_id for t in dati.titolari if t.squadra_id == sq]
                rosa[sq] = (componenti.giocatori_squadra(s, sq, correnti), correnti)

if det is None:
    st.error("Partita non trovata.")
    st.stop()

casa, trasf = dati.nomi_squadre.get(dati.casa_id, ""), dati.nomi_squadre.get(dati.trasferta_id, "")
st.header(f"{casa} – {trasf}")
giornata = f" · Giornata {partita.giornata}" if partita.giornata else ""
st.caption(f"{componenti.data_italiana(partita.data_utc)}{giornata} · formazioni {partita.stato_formazioni}")

for riga in componenti.righe_contesto(dati):
    st.markdown(f"- {riga}")

if cambi:
    st.subheader("Cambi rispetto alle formazioni probabili")
    for riga in cambi:
        st.markdown(f"- {riga}")

st.subheader("Candidati all'ammonizione")
righe = componenti.righe_tabella(det.candidati, dati.nomi_squadre, det.tipster)
if not righe:
    st.info("Nessun candidato: mancano le formazioni e lo storico dei titolari.")
else:
    tabella = pd.DataFrame(righe, columns=list(componenti.COLONNE_TABELLA))
    st.dataframe(
        tabella.style.map(componenti.colore_valore, subset=["Valore"]),
        hide_index=True,
        width="stretch",
    )

nomi = {c.giocatore_id: c.nome for c in det.candidati}

for c in det.candidati:
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
        st.markdown(f"[Sofascore]({info['link']})")

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
            st.rerun()
        if scelto is None and c.giocatore_id in dati.duelli_manuali:
            with apri() as s:
                componenti.rimuovi_duello(s, partita_id, c.giocatore_id)
            del st.session_state[f"duello_{c.giocatore_id}"]  # torna l'avversario automatico
            st.rerun()

        with st.form(f"form_quota_{c.giocatore_id}"):
            testo_quota = st.text_input("Quota", key=f"quota_{c.giocatore_id}", placeholder="es. 2,10")
            invia = st.form_submit_button("Salva quota", key=f"salva_quota_{c.giocatore_id}")
        if invia:
            try:
                quote[c.giocatore_id] = converti_quota(testo_quota)
            except ValueError as errore:
                st.error(str(errore))
            else:
                st.rerun()

        st.page_link(
            "pages/2_Giocate.py",
            label="Registra giocata",
            query_params={"partita": partita_id, "giocatore": c.giocatore_id},
        )

if det.candidati:
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
            st.rerun()

if rosa:
    st.subheader("Formazioni probabili")
    st.caption("Correggi gli 11 di ciascuna squadra; la classifica si aggiorna al salvataggio.")
    for sq, (giocatori, correnti) in rosa.items():
        nomi_rosa = dict(giocatori)
        st.multiselect(
            dati.nomi_squadre.get(sq, str(sq)),
            [i for i, _ in giocatori],
            default=correnti,
            format_func=lambda i, n=nomi_rosa: n.get(i, str(i)),
            key=f"probabili_{sq}",
        )
    if st.button("Salva formazioni probabili", key="salva_probabili"):
        with apri() as s:
            salva_probabili(
                s, partita_id, {sq: list(st.session_state[f"probabili_{sq}"]) for sq in rosa}
            )
        st.rerun()
