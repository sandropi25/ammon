"""Schermata di benvenuto e accesso: gettone "Ricordami" firmato, attese dopo i tentativi
sbagliati, menu nascosto prima dell'accesso, uscita."""
from datetime import datetime, timedelta, timezone

import pytest
from ayuda_app import PAGINA_APP, RADICE, sessione_db, url_db, visibile  # noqa: F401
from db_prova import PARTITA_FUTURA, popola
from streamlit.testing.v1 import AppTest

import auth
import stile
from ammonizioni.db.modelli import Partita

ADESSO = 1_800_000_000.0
GIORNO = 86_400


@pytest.fixture(autouse=True)
def _senza_errori_precedenti(monkeypatch):
    """Gli errori recenti sono di tutto il processo: ogni test parte da zero e non dorme."""
    auth._errori_recenti.clear()
    attese = []
    monkeypatch.setattr(auth, "_dormi", attese.append)
    yield attese
    auth._errori_recenti.clear()


# ---------------------------------------------------------------- gettone

def test_gettone_valido_per_30_giorni():
    g = auth.crea_gettone("segreta", ADESSO)
    assert g.startswith("v1.") and "segreta" not in g
    assert auth.gettone_valido(g, "segreta", ADESSO)
    assert auth.gettone_valido(g, "segreta", ADESSO + 29 * GIORNO)
    assert not auth.gettone_valido(g, "segreta", ADESSO + 30 * GIORNO + 1)  # scaduto


def test_gettone_falso_o_di_un_altra_password():
    g = auth.crea_gettone("segreta", ADESSO)
    assert not auth.gettone_valido(g, "nuova", ADESSO)  # password cambiata: non vale più
    versione, scadenza, firma = g.split(".")
    altra = "0" if firma[0] != "0" else "1"
    assert not auth.gettone_valido(f"{versione}.{scadenza}.{altra}{firma[1:]}", "segreta", ADESSO)
    # scadenza allungata a mano: la firma non torna
    assert not auth.gettone_valido(f"v1.{int(scadenza) + 10}.{firma}", "segreta", ADESSO)
    for falso in (None, "", "abc", "v2.1.2", "v1.x.y", "v1..", "v1.1.2.3", "v1." + "9" * 300):
        assert not auth.gettone_valido(falso, "segreta", ADESSO)


def test_gettone_con_scadenza_troppo_lontana_non_vale():
    g = auth.crea_gettone("segreta", ADESSO, giorni=365)
    assert not auth.gettone_valido(g, "segreta", ADESSO)


def test_script_cookie_scrive_e_cancella():
    g = auth.crea_gettone("segreta", ADESSO)
    scrivi = auth.script_cookie(g)
    assert f"cartellino_accesso={g}; Max-Age={30 * GIORNO}" in scrivi and "SameSite=Strict" in scrivi
    assert "Max-Age=0" in auth.script_cookie(None)
    with pytest.raises(ValueError):
        auth.script_cookie("x'; alert(1); '")


def test_attese_dopo_i_tentativi_sbagliati():
    assert [auth.attesa_dopo_errori(n) for n in range(9)] == [0, 0, 0, 1, 2, 3, 4, 5, 5]


# ---------------------------------------------------------------- nelle pagine

def _prepara(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(days=2)


def _app(password="x"):
    at = AppTest.from_file(PAGINA_APP, default_timeout=30)
    at.secrets["password"] = password
    at.switch_page("pagine/0_Partite.py")
    return at


def _entra(at, password, ricordami=False):
    at.text_input(key="password_accesso").set_value(password)
    at.checkbox(key="ricordami").check() if ricordami else None
    return at.button(key="entra").click().run()


def test_schermata_di_benvenuto_senza_dati(sessione_db):
    _prepara(sessione_db)
    at = _app().run()
    assert not at.exception
    t = visibile(at)
    assert "Benvenuto nel mondo del <span>Yellow</span>!" in t
    assert "Pronostici sui cartellini di Serie A e Liga" in t
    assert "Casa FC" not in t and "Dati aggiornati" not in t and "Dati non ancora" not in t
    assert at.checkbox(key="ricordami").label == "Ricordami su questo dispositivo"
    assert at.button(key="cambia_tema")  # il tema si cambia anche prima di entrare


def test_tentativi_sbagliati_poi_attesa(sessione_db, _senza_errori_precedenti):
    _prepara(sessione_db)
    at = _app().run()
    for _ in range(5):
        _entra(at, "sbagliata")
        assert "Password non corretta" in at.error[0].value
    assert _senza_errori_precedenti == [1.0, 2.0]  # dal quarto tentativo
    _entra(at, "x")
    assert not at.exception and "Casa FC" in visibile(at)
    assert _senza_errori_precedenti == [1.0, 2.0, 3.0]  # anche il tentativo giusto aspetta


def test_ricordami_scrive_il_cookie_firmato(sessione_db):
    _prepara(sessione_db)
    at = _app().run()
    _entra(at, "x", ricordami=True)
    assert not at.exception
    script = [h.value for h in at.html if "cartellino_accesso=" in str(h.value)]
    assert len(script) == 1
    gettone = script[0].split("cartellino_accesso=")[1].split(";")[0]
    assert auth.gettone_valido(gettone, "x", datetime.now(timezone.utc).timestamp())
    assert "x" not in gettone.split(".")[1:]  # la password non c'è


def test_senza_ricordami_nessun_cookie(sessione_db):
    _prepara(sessione_db)
    at = _app().run()
    _entra(at, "x")
    assert not [h for h in at.html if "cartellino_accesso=" in str(h.value)]


def test_cookie_valido_entra_senza_password(sessione_db, monkeypatch):
    _prepara(sessione_db)
    gettone = auth.crea_gettone("x", datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr(auth, "_cookie", lambda: gettone)
    at = _app().run()
    assert not at.exception
    assert "Casa FC" in visibile(at) and not at.text_input


def test_cookie_falso_o_scaduto_non_basta(sessione_db, monkeypatch):
    _prepara(sessione_db)
    vecchio = auth.crea_gettone("x", datetime.now(timezone.utc).timestamp() - 31 * GIORNO)
    for gettone in ("v1.123.abc", vecchio, auth.crea_gettone("altra", datetime.now(timezone.utc).timestamp())):
        monkeypatch.setattr(auth, "_cookie", lambda g=gettone: g)
        at = _app().run()
        assert "Casa FC" not in visibile(at) and at.text_input


def test_esci_cancella_il_cookie_e_richiede_la_password(sessione_db, monkeypatch):
    _prepara(sessione_db)
    gettone = auth.crea_gettone("x", datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr(auth, "_cookie", lambda: gettone)
    at = AppTest.from_file(PAGINA_APP, default_timeout=30)
    at.secrets["password"] = "x"
    at.switch_page("pagine/3_Impostazioni.py")
    at.run()
    assert not at.exception
    at.button(key="esci").click().run()
    assert not at.exception
    assert "Benvenuto nel mondo del" in visibile(at)
    assert any("Max-Age=0" in str(h.value) for h in at.html)  # cookie cancellato


def test_senza_password_nessun_pulsante_esci(sessione_db):
    _prepara(sessione_db)
    at = AppTest.from_file(PAGINA_APP, default_timeout=30)
    at.switch_page("pagine/3_Impostazioni.py")
    at.run()
    assert not at.exception
    assert not [b for b in at.button if b.key == "esci"]


def test_accesso_valido_con_segreti_illeggibili_e_falso(monkeypatch):
    def guasto():
        raise auth.SegretiIllegibili("rotto")

    monkeypatch.setattr(auth, "_password_attesa", guasto)
    assert auth.accesso_valido() is False


def test_titolo_di_benvenuto_con_escape():
    html = stile.benvenuto()
    assert "Benvenuto nel mondo del <span>Yellow</span>!" in html
    assert "cr-logo" in html


def test_css_accesso_nasconde_il_menu_e_rispetta_riduci_movimento():
    for tema in ("scuro", "chiaro"):
        css = stile.css_accesso(tema)
        assert '[data-testid="stHeader"]' in css and "display: none" in css
        assert "prefers-reduced-motion" in css and "@keyframes cr-deriva" in css


def test_router_nasconde_il_menu_prima_dell_accesso():
    testo = (RADICE / "app" / "Partite.py").read_text(encoding="utf-8")
    assert '"top" if auth.accesso_valido() else "hidden"' in testo
