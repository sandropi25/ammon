"""Riquadro "Incolla formazione ufficiale" del dettaglio partita: quando ESPN e' in ritardo
(le ufficiali escono ~60 minuti prima, ESPN le ha 37-46 minuti prima) l'utente incolla il
testo di un giornale e l'app la salva come formazione ufficiale."""
from __future__ import annotations

import streamlit as st

import cache_dati
from ammonizioni.caricamento import incolla
from ammonizioni.db.modelli import Partita
from ammonizioni.db.sessione import apri

ESEMPIO = (
    "es. ATALANTA (4-2-3-1): Carnesecchi; Bellanova, Scalvini, Kolasinac, Zappacosta; "
    "Kessié, Ederson; Elmas, De Ketelaere, Zalewski; Krstovic. All. Sarri"
)


def _squadra(partita_id: int, squadra_id: int, nome: str) -> None:
    testo = st.text_area(
        f"Formazione {nome}", key=f"incolla_{partita_id}_{squadra_id}",
        placeholder=ESEMPIO, height=110,
    )
    if not testo.strip():
        return
    scelte = st.session_state.setdefault(f"scelte_incolla_{partita_id}_{squadra_id}", {})
    with apri() as s:
        partita = s.get(Partita, partita_id)
        lettura = incolla.riconosci(s, partita, squadra_id, testo, scelte)
    if lettura.titolari:
        st.caption(
            f"Riconosciuti {len(lettura.titolari)}/11: "
            + ", ".join(lettura.nomi[g] for g, _ in lettura.titolari)
        )
    for scritto in lettura.mancanti:
        st.error(f"«{scritto}» non è tra i giocatori del {nome}: controlla come è scritto.")
    for scritto, opzioni in lettura.ambigui:
        nomi = dict(opzioni)
        scelto = st.selectbox(
            f"«{scritto}»: quale?", [None] + list(nomi),
            format_func=lambda g, n=nomi: "scegli…" if g is None else n[g],
            key=f"ambiguo_{partita_id}_{squadra_id}_{scritto}",
        )
        if scelto is not None:
            scelte[scritto] = scelto
            st.rerun()
    n = len(lettura.titolari) + len(lettura.mancanti) + len(lettura.ambigui)
    if n != incolla.TITOLARI:
        st.warning(f"Nel testo ci sono {n} giocatori: ne servono 11.")
    if st.button(
        f"Salva formazione {nome}", key=f"salva_incolla_{partita_id}_{squadra_id}",
        type="primary", disabled=not lettura.pronta,
    ):
        with apri() as s:
            incolla.salva(s, s.get(Partita, partita_id), squadra_id, lettura.titolari)
        st.session_state.pop(f"scelte_incolla_{partita_id}_{squadra_id}", None)
        st.session_state[f"salvata_incolla_{partita_id}"] = nome
        cache_dati.svuota()
        st.rerun()


def riquadro(partita_id: int, squadre: list[tuple[int, str]], aperto: bool) -> None:
    """Un'area di testo per squadra; ogni squadra si salva da sola."""
    salvata = st.session_state.pop(f"salvata_incolla_{partita_id}", None)
    if salvata:
        st.success(f"Formazione ufficiale del {salvata} salvata: probabilità ricalcolate.")
    with st.expander("Formazioni ufficiali in ritardo? Incollale qui", expanded=aperto):
        st.caption(
            "Incolla la formazione di una squadra come la scrivono i giornali: linee separate "
            "dal punto e virgola, dal portiere all'attacco. Squadra, modulo, panchina e "
            "allenatore vengono ignorati."
        )
        colonne = st.columns(len(squadre))
        for colonna, (squadra_id, nome) in zip(colonne, squadre):
            with colonna:
                _squadra(partita_id, squadra_id, nome)
