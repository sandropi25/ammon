"""App beta dei marcatori: separata dall'app dei cartellini (stesso database, sola lettura).
Su Streamlit Community Cloud: main file `app_marcatori/Marcatori.py`, stessi Secrets dell'app
dei cartellini. Riusa accesso e grafica dalla cartella app/ senza modificarla."""
import sys
from pathlib import Path

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
if senza_password:
    st.error("App chiusa: nei Secrets manca la riga `password` (come nell'app dei cartellini).")
    st.stop()
auth.richiedi_password()

st.title("⚽ Marcatori · beta")
st.info(
    "Sto costruendo il modello dei marcatori: prima lo verifico sulle stagioni passate, poi qui "
    "compariranno le partite dei 4 campionati con i giocatori più probabili a segnare."
)
