"""Accesso con password condivisa (solo se configurata nei segreti)."""
import hmac

import streamlit as st


def _password_attesa() -> str | None:
    try:
        valore = st.secrets.get("password")
    except Exception:  # nessun file dei segreti: sviluppo locale
        return None
    return str(valore) if valore else None


def richiedi_password() -> bool:
    """Se i segreti hanno `password` chiede la password e ferma la pagina (st.stop)
    finché non è giusta; senza segreto passa e restituisce True."""
    attesa = _password_attesa()
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
