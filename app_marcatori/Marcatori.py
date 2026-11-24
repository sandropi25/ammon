"""App beta dei marcatori: separata dall'app dei cartellini (stesso database, sola lettura).
Su Streamlit Community Cloud: main file `app_marcatori/Marcatori.py`, stessi Secrets dell'app
dei cartellini. Riusa accesso e grafica dalla cartella app/ senza modificarla."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "app"))
sys.path.insert(0, str(RADICE / "src"))

import streamlit as st  # noqa: E402

import auth  # noqa: E402

st.set_page_config(page_title="Marcatori (beta)", page_icon="⚽", layout="wide")
try:  # online la password e' obbligatoria: senza, l'app resta chiusa (mai aperta a tutti)
    senza_password = auth._password_attesa() is None
except auth.SegretiIllegibili:
    senza_password = True
if senza_password and os.environ.get("MARCATORI_LOCALE") != "1":  # solo prove sul PC
    st.error("App chiusa: nei Secrets manca la riga `password` (come nell'app dei cartellini).")
    st.stop()
auth.richiedi_password()

from sqlalchemy import select  # noqa: E402

from ammonizioni import config  # noqa: E402
from ammonizioni.config import CAMPIONATI, NOMI_CAMPIONATI  # noqa: E402
from ammonizioni.db import repo  # noqa: E402
from ammonizioni.db.modelli import Giocatore, Partita, Squadra  # noqa: E402
from ammonizioni.db.sessione import apri  # noqa: E402
from ammonizioni.marcatori.pronostici import pronostica  # noqa: E402

FUSO = ZoneInfo("Europe/Rome")
GIORNI = 7
MOSTRATI = 8
GIORNI_SETTIMANA = ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom")
RUOLI = {"F": "Att", "M": "Cen", "D": "Dif", "G": "Por", "?": ""}
FORMAZIONI = {
    "ufficiali": "✅ formazioni ufficiali",
    "probabili": "🟡 formazioni probabili",
    "stimate": "⚪ formazioni stimate dalle ultime partite",
}


@st.cache_data(ttl=1800, show_spinner="Calcolo i pronostici…")
def carica_pronostici(db: str, blocco: datetime) -> list[dict]:
    """Pronostici delle partite dei 4 campionati nei prossimi 7 giorni (ricalcolati ogni 30')."""
    with apri(db) as s:
        partite = list(s.scalars(
            select(Partita)
            .where(
                Partita.competizione_id.in_(CAMPIONATI),
                Partita.stato == "NS",
                Partita.data_utc > blocco,
                Partita.data_utc < blocco + timedelta(days=GIORNI),
            )
            .order_by(Partita.data_utc, Partita.id)
        ))
        pronostici = {pr.partita_id: pr for pr in pronostica(s, partite)}
        ids = {x.giocatore_id for pr in pronostici.values() for x in pr.previsioni}
        nomi_g = dict(s.execute(select(Giocatore.id, Giocatore.nome).where(Giocatore.id.in_(ids))).all()) if ids else {}
        squadre = {p.casa_id for p in partite} | {p.trasferta_id for p in partite}
        nomi_s = dict(s.execute(select(Squadra.id, Squadra.nome).where(Squadra.id.in_(squadre))).all()) if squadre else {}
        coeff = repo.leggi_impostazione(s, "marcatori_coefficienti", None) or {}
        risultato = []
        for p in partite:
            pr = pronostici[p.id]
            risultato.append({
                "campionato": p.competizione_id,
                "data": p.data_utc if p.data_utc.tzinfo else p.data_utc.replace(tzinfo=timezone.utc),
                "casa": nomi_s.get(p.casa_id, "?"), "trasferta": nomi_s.get(p.trasferta_id, "?"),
                "casa_id": p.casa_id,
                "formazioni": pr.formazioni,
                "giocatori": [
                    {"nome": nomi_g.get(x.giocatore_id, "?"), "casa": x.squadra_id == p.casa_id,
                     "ruolo": RUOLI.get(x.ruolo, ""), "titolare": x.titolare, "p": x.probabilita}
                    for x in pr.previsioni[:MOSTRATI]
                ],
                "stimati": coeff.get("stimati_utc"),
            })
        return risultato


st.title("⚽ Marcatori · beta")
st.caption(
    "Probabilità che il giocatore segni almeno un gol. Modello: gol attesi della squadra "
    "(attacco, difesa avversaria, casa/trasferta) × ritmo del giocatore (gol e tiri) × minuti "
    "attesi, con forma recente, derby, rientro da assenza e minuti degli ultimi 7 giorni."
)
with st.expander("Quanto è preciso (verifica sulla stagione 2025)"):
    st.markdown(
        "Allenato sul 2024 e provato su 1.849 partite del 2025-26 mai viste:\n\n"
        "| | Almeno uno dei primi 3 segna | Il primo della lista segna |\n|---|---|---|\n"
        "| **Modello** | **60,5%** | **33,1%** |\n| Scelta semplice (gol a partita) | 51,9% | 26,0% |\n\n"
        "Per campionato (primi 3): Liga 65%, Premier 61%, Ligue 1 59%, Serie A 56%. "
        "Le percentuali sono calibrate: su 100 giocatori dati al 30%, segnano circa in 30."
    )

adesso = datetime.now(timezone.utc)
blocco = adesso.replace(minute=0, second=0, microsecond=0)
dati = carica_pronostici(config.url_database(), blocco)
dati = [d for d in dati if d["data"] > adesso]

scelta = st.pills(
    "Campionato", [NOMI_CAMPIONATI[c] for c in CAMPIONATI], default=NOMI_CAMPIONATI[CAMPIONATI[0]],
    label_visibility="collapsed",
)
codice = next((c for c in CAMPIONATI if NOMI_CAMPIONATI[c] == scelta), CAMPIONATI[0])
partite = [d for d in dati if d["campionato"] == codice]
if not partite:
    st.info(f"Nessuna partita di {NOMI_CAMPIONATI[codice]} nei prossimi {GIORNI} giorni.")

for d in partite:
    ora = d["data"].astimezone(FUSO)
    with st.container(border=True):
        st.markdown(
            f"**{d['casa']} – {d['trasferta']}**  ·  "
            f"{GIORNI_SETTIMANA[ora.weekday()]} {ora:%d/%m %H:%M}"
        )
        st.caption(FORMAZIONI.get(d["formazioni"], "formazioni non ancora disponibili"))
        if not d["giocatori"]:
            st.write("Pronostico non disponibile: mancano le formazioni.")
            continue
        for g in d["giocatori"]:
            squadra = d["casa"] if g["casa"] else d["trasferta"]
            panchina = "" if g["titolare"] else " · dalla panchina"
            c1, c2 = st.columns([3, 2])
            c1.markdown(f"{g['nome']}  \n<small>{squadra} · {g['ruolo']}{panchina}</small>",
                        unsafe_allow_html=True)
            c2.progress(min(g["p"] / 0.6, 1.0), text=f"{g['p']:.0%}")

st.caption("Beta: le formazioni ufficiali sostituiscono quelle stimate circa un'ora prima del via.")
