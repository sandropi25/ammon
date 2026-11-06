"""Menu dei campionati: "Serie A ▾" e "Liga ▾" con le partite della giornata in corso,
"Tutti", scelta del campionato condivisa e link al calendario completo."""
from datetime import datetime, timedelta, timezone

from ayuda_app import (  # noqa: F401
    PAGINA_CALENDARIO, PAGINA_DETTAGLIO, PAGINA_PARTITE, avvia, campionato_scelto,
    scegli_campionato, sessione_db, url_db, visibile,
)
from db_prova import PARTITA_FUTURA, popola

import componenti
import stile
from ammonizioni.db.modelli import Partita, Squadra


def _riga(**campi):
    base = dict(
        id=5, quando="", giornata=11, casa="Inter", trasferta="Milan", arbitro=None,
        calda=False, formazioni="probabili", campionato="Serie A", ora="20:45",
        data_utc=datetime(2026, 11, 8, 19, 45, tzinfo=timezone.utc),
    )
    base.update(campi)
    return componenti.RigaPartita(**base)


# ---------------------------------------------------------------- HTML

def test_voce_menu_con_orario_stemmi_e_fuoco():
    html = stile.voce_menu(_riga(calda=True))
    assert "<b>20:45</b>" in html and ">dom<" in html  # domenica, ora di Roma
    assert ">IN</span>Inter" in html and ">MI</span>Milan" in html
    assert "🔥" in html
    assert "🔥" not in stile.voce_menu(_riga())


def test_voce_menu_partita_giocata_mostra_il_risultato():
    html = stile.voce_menu(_riga(finita=True, gol_casa=2, gol_trasferta=1, stato="FT"))
    assert "<b>2–1</b>" in html and "fin." in html


def test_voce_menu_fa_l_escape():
    html = stile.voce_menu(_riga(casa="<script>x</script>", ora="<b>"))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_titolo_menu():
    assert "Giornata 11" in stile.titolo_menu("Giornata 11", 10)
    assert "· 10 partite" in stile.titolo_menu("Giornata 11", 10)
    assert "· 1 partita" in stile.titolo_menu("Giornata <11>", 1)
    assert "&lt;11&gt;" in stile.titolo_menu("Giornata <11>", 1)


def test_aprire_la_tendina_sceglie_il_campionato(monkeypatch):
    stato = {"menu_liga": True, "campionato": "Serie A"}
    monkeypatch.setattr(stile.st, "session_state", stato)
    stile._menu_aperto("menu_liga", "Liga")
    assert stato["campionato"] == "Liga"
    stato["menu_liga"] = False  # chiudendola non cambia nulla
    stato["campionato"] = "Tutti"
    stile._menu_aperto("menu_liga", "Liga")
    assert stato["campionato"] == "Tutti"
    stile.scegli_campionato("Pallavolo")  # valore sconosciuto: ignorato
    assert stato["campionato"] == "Tutti"


def test_chiavi_dei_menu():
    assert stile.chiave_menu("Serie A") == "menu_serie-a"
    assert stile.chiave_menu("Liga") == "menu_liga"


# ---------------------------------------------------------------- nelle pagine

def _prepara(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(days=2)
        s.add_all([Squadra(id=601, nome="Real Liga"), Squadra(id=602, nome="Barca Liga")])
        s.flush()
        s.add(Partita(id=900, data_utc=datetime.now(timezone.utc) + timedelta(days=3),
                      competizione_id=140, stagione=2026, giornata=11, casa_id=601,
                      trasferta_id=602, stato="NS"))


def _voci(at):
    return [m.value for m in at.markdown if 'class="cr-voce-menu"' in m.value]


def test_tendina_chiusa_non_legge_le_partite(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    assert _voci(at) == []


def test_tendina_aperta_mostra_la_giornata_e_porta_al_dettaglio(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    at.session_state["menu_serie-a"] = True
    at.run()
    assert not at.exception
    t = visibile(at)
    assert "Giornata 7" in t  # giornata in corso della Serie A nei dati di prova
    voci = _voci(at)
    assert voci and any("Casa FC" in v and "🔥" in v for v in voci)  # il derby è caldo
    link = {(e.proto.label, e.proto.page) for e in at.get("page_link")}
    assert any(lbl == "Casa FC – Trasferta FC" for lbl, _ in link)
    assert any(lbl == "Tutto il calendario →" for lbl, _ in link)
    assert "Real Liga" not in t  # la tendina della Liga resta chiusa


def test_tendina_della_liga(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    at.session_state["menu_liga"] = True
    at.run()
    assert not at.exception
    assert "Giornata 11" in visibile(at)
    assert any("Real Liga" in v and "🔥" not in v for v in _voci(at))


def test_menu_anche_nel_dettaglio(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    assert at.button(key="campionato_tutti")


def test_tutti_dal_pulsante(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    scegli_campionato(at, "Tutti")
    assert campionato_scelto(at) == "Tutti" and at.query_params.get("campionato") == "tutti"
    assert "Real Liga" in visibile(at) and "Casa FC" in visibile(at)


def test_link_al_calendario_porta_il_suo_campionato(sessione_db):
    """"Tutto il calendario →" della Liga apre il calendario della Liga anche se la scelta
    era la Serie A; poi la scelta resta la Liga."""
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    assert campionato_scelto(at) == "Serie A"
    at.query_params["campionato"] = "liga"
    at.switch_page("pagine/5_Calendario.py").run()
    assert not at.exception
    assert campionato_scelto(at) == "Liga"
    assert "Real Liga" in visibile(at)
    at.switch_page("pagine/0_Partite.py").run()
    assert campionato_scelto(at) == "Liga"
