"""Accesso con password condivisa (solo se configurata nei segreti).

- Senza file dei segreti (sviluppo locale) si entra senza password; un file dei segreti
  illeggibile blocca l'app (fail-closed): mai avviare senza password per un errore.
- Schermata di benvenuto con la password; confronto a tempo costante; dopo alcuni tentativi
  sbagliati (nella sessione o in tutto il processo nell'ultimo minuto) una breve attesa.
- "Ricordami su questo dispositivo": un cookie con un gettone firmato (HMAC-SHA256 con una
  chiave ricavata dalla password) che scade dopo 30 giorni. La password non viene mai
  salvata; cambiandola tutti i gettoni smettono di valere."""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

ERRORE_NESSUN_SEGRETO = "no-secrets-found"  # error_id di Streamlit: nessun file dei segreti

CHIAVE_AUTENTICATO = "autenticato"
CHIAVE_ERRORI = "accesso_errori"  # tentativi sbagliati di questa sessione
CHIAVE_GETTONE = "accesso_gettone_da_scrivere"  # cookie da scrivere dopo l'accesso
CHIAVE_USCITO = "accesso_uscito"  # dopo "Esci" il cookie (già letto) non vale più
COOKIE = "cartellino_accesso"
VERSIONE_GETTONE = "v1"
GIORNI_RICORDAMI = 30
SECONDI_GIORNO = 86_400
TENTATIVI_LIBERI = 3  # dal quarto tentativo sbagliato si aspetta
ATTESA_MASSIMA = 5.0  # secondi
FINESTRA_ERRORI = 60.0  # secondi: errori recenti di tutto il processo

_dormi = time.sleep  # sostituibile nei test
_lock = threading.Lock()
_errori_recenti: deque[float] = deque()


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


# ---------------------------------------------------------------- gettone "Ricordami"

def _chiave_firma(password: str) -> bytes:
    """Chiave HMAC ricavata dalla password (la password non finisce nel gettone)."""
    return hmac.new(password.encode(), b"cartellino-ricordami", hashlib.sha256).digest()


def _firma(password: str, scadenza: int) -> str:
    messaggio = f"{VERSIONE_GETTONE}.{scadenza}".encode()
    return hmac.new(_chiave_firma(password), messaggio, hashlib.sha256).hexdigest()


def crea_gettone(password: str, adesso: float, giorni: int = GIORNI_RICORDAMI) -> str:
    """"v1.<scadenza unix>.<firma esadecimale>"."""
    scadenza = int(adesso) + giorni * SECONDI_GIORNO
    return f"{VERSIONE_GETTONE}.{scadenza}.{_firma(password, scadenza)}"


def gettone_valido(gettone: str | None, password: str, adesso: float) -> bool:
    """Firma giusta (confronto a tempo costante) e non scaduto; una scadenza oltre i 30
    giorni da adesso non è stata emessa dall'app e non vale."""
    if not gettone or not isinstance(gettone, str) or len(gettone) > 200:
        return False
    parti = gettone.split(".")
    if len(parti) != 3 or parti[0] != VERSIONE_GETTONE or not parti[1].isdigit():
        return False
    scadenza = int(parti[1])
    if not adesso < scadenza <= adesso + GIORNI_RICORDAMI * SECONDI_GIORNO + 60:
        return False
    return hmac.compare_digest(parti[2].encode(), _firma(password, scadenza).encode())


def script_cookie(gettone: str | None, giorni: int = GIORNI_RICORDAMI) -> str:
    """Script che scrive (o, senza gettone, cancella) il cookie del gettone."""
    if gettone is None:
        valore, durata = "", 0
    else:
        if not all(c.isalnum() or c == "." for c in gettone):
            raise ValueError("gettone non valido")
        valore, durata = gettone, giorni * SECONDI_GIORNO
    return (
        "<script>document.cookie = "
        f"'{COOKIE}={valore}; Max-Age={durata}; Path=/; SameSite=Strict'"
        " + (location.protocol === 'https:' ? '; Secure' : '');</script>"
    )


def _cookie() -> str | None:
    try:
        return st.context.cookies.get(COOKIE)
    except Exception:  # noqa: BLE001 - senza contesto (test, versioni diverse) nessun cookie
        return None


# ---------------------------------------------------------------- tentativi sbagliati

def attesa_dopo_errori(errori: int) -> float:
    """Secondi da aspettare prima di controllare un nuovo tentativo: 0 per i primi
    tentativi, poi 1, 2, ... fino a 5."""
    if errori < TENTATIVI_LIBERI:
        return 0.0
    return min(float(errori - TENTATIVI_LIBERI + 1), ATTESA_MASSIMA)


def _errori_processo(adesso: float) -> int:
    with _lock:
        while _errori_recenti and adesso - _errori_recenti[0] > FINESTRA_ERRORI:
            _errori_recenti.popleft()
        return len(_errori_recenti)


def _registra_errore(adesso: float) -> None:
    with _lock:
        _errori_recenti.append(adesso)
    st.session_state[CHIAVE_ERRORI] = st.session_state.get(CHIAVE_ERRORI, 0) + 1


# ---------------------------------------------------------------- Streamlit

def accesso_valido() -> bool:
    """True se si può entrare: nessuna password configurata, accesso già fatto in questa
    sessione o cookie "Ricordami" valido. False anche con i segreti illeggibili. Non mostra
    nulla (il punto d'ingresso lo usa per nascondere il menu prima dell'accesso)."""
    try:
        attesa = _password_attesa()
    except SegretiIllegibili:
        return False
    if attesa is None or st.session_state.get(CHIAVE_AUTENTICATO):
        return True
    if not st.session_state.get(CHIAVE_USCITO) and gettone_valido(_cookie(), attesa, time.time()):
        st.session_state[CHIAVE_AUTENTICATO] = True
        return True
    return False


def _prova_accesso(attesa: str, inserita: str, ricordami: bool) -> bool:
    adesso = time.time()
    errori = max(st.session_state.get(CHIAVE_ERRORI, 0), _errori_processo(adesso))
    pausa = attesa_dopo_errori(errori)
    if pausa:
        _dormi(pausa)
    if inserita and hmac.compare_digest(inserita.encode(), attesa.encode()):
        st.session_state[CHIAVE_AUTENTICATO] = True
        st.session_state[CHIAVE_ERRORI] = 0
        st.session_state.pop(CHIAVE_USCITO, None)
        if ricordami:
            st.session_state[CHIAVE_GETTONE] = crea_gettone(attesa, adesso)
        return True
    _registra_errore(adesso)
    return False


def _schermata_accesso(attesa: str) -> None:
    import stile  # qui: stile importa il motore, serve solo per la grafica

    stile.applica_stile_accesso()
    if st.session_state.pop(CHIAVE_USCITO + "_cookie", False):
        st.html(script_cookie(None), unsafe_allow_javascript=True)
    with st.container(key="accesso"):
        st.markdown(stile.benvenuto(), unsafe_allow_html=True)
        with st.form("modulo_accesso", border=False, enter_to_submit=True):
            inserita = st.text_input(
                "Password", type="password", key="password_accesso",
                placeholder="La password che ti hanno dato",
            )
            ricordami = st.checkbox("Ricordami su questo dispositivo", key="ricordami")
            entra = st.form_submit_button(
                "Entra", type="primary", key="entra", width="stretch"
            )
        if entra:
            if _prova_accesso(attesa, inserita or "", ricordami):
                st.rerun()
            st.error("Password non corretta: controlla e riprova.")
        st.caption("Ricordami salva sul dispositivo solo un gettone firmato, valido 30 giorni.")


def richiedi_password() -> bool:
    """Se i segreti hanno `password` e non si è ancora entrati mostra la schermata di
    benvenuto e ferma la pagina (st.stop); senza segreto passa e restituisce True."""
    try:
        attesa = _password_attesa()
    except SegretiIllegibili:
        st.error("Impossibile leggere la configurazione della password: controlla il file dei segreti.")
        st.stop()
        return False
    if attesa is None:
        return True
    if accesso_valido():
        gettone = st.session_state.pop(CHIAVE_GETTONE, None)
        if gettone:
            st.html(script_cookie(gettone), unsafe_allow_javascript=True)
        return True
    _schermata_accesso(attesa)
    st.stop()
    return False


def esci() -> None:
    """Esce da questa sessione e cancella il cookie "Ricordami" del dispositivo."""
    st.session_state[CHIAVE_AUTENTICATO] = False
    st.session_state[CHIAVE_USCITO] = True
    st.session_state[CHIAVE_USCITO + "_cookie"] = True
    st.session_state.pop(CHIAVE_GETTONE, None)


def password_configurata() -> bool:
    try:
        return _password_attesa() is not None
    except SegretiIllegibili:
        return True
