"""Accesso con password condivisa (solo se configurata nei segreti)."""
import hmac

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


ERRORE_NESSUN_SEGRETO = "no-secrets-found"  # error_id di Streamlit: nessun file dei segreti


class SegretiIllegibili(Exception):
    """Il file dei segreti esiste ma non si può leggere o interpretare."""


def _password_attesa() -> str | None:
    """Password configurata; None solo se non c'è alcun file dei segreti (sviluppo locale).
    Ogni altro errore solleva SegretiIllegibili: mai avviare senza password per un errore."""
    try:
        valore = st.secrets.get("password")
    except StreamlitSecretNotFoundError as errore:
        # Streamlit usa la stessa classe anche per file non interpretabili o percorsi non validi:
        # passa solo il caso strutturato "nessun segreto trovato"; il resto blocca l'app.
        if getattr(errore, "error_id", None) == ERRORE_NESSUN_SEGRETO:
            return None
        raise SegretiIllegibili(str(errore)) from errore
    except Exception as errore:
        raise SegretiIllegibili(str(errore)) from errore
    return str(valore) if valore else None


def richiedi_password() -> bool:
    """Se i segreti hanno `password` chiede la password e ferma la pagina (st.stop)
    finché non è giusta; senza segreto passa e restituisce True."""
    try:
        attesa = _password_attesa()
    except SegretiIllegibili:
        st.error("Impossibile leggere la configurazione della password: controlla il file dei segreti.")
        st.stop()
        return False
    if attesa is None or st.session_state.get("autenticato"):
        return True
    inserita = st.text_input("Password", type="password", key="password_accesso")
    if inserita and hmac.compare_digest(inserita.encode(), attesa.encode()):
        st.session_state["autenticato"] = True
        st.rerun()
    if inserita:
        st.error("Password errata")
    st.stop()
    return False
