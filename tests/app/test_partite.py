from datetime import datetime, timedelta, timezone

from ayuda_app import PAGINA_PARTITE, avvia, sessione_db, url_db, visibile
from db_prova import PARTITA_FUTURA, popola
from streamlit.testing.v1 import AppTest

from ammonizioni.db.modelli import Partita, UltimoAggiornamento


def _prepara(sessione_db, *, completo=True):
    with sessione_db() as s:
        popola(s)
        p = s.get(Partita, PARTITA_FUTURA)
        p.data_utc = datetime.now(timezone.utc) + timedelta(days=2)
        # una partita oltre i 7 giorni: non deve comparire
        s.add(
            Partita(
                id=101, data_utc=datetime.now(timezone.utc) + timedelta(days=20),
                competizione_id=135, stagione=2026, giornata=9, casa_id=1, trasferta_id=2,
                stato="NS",
            )
        )
        s.add(
            UltimoAggiornamento(
                job="notte", quando_utc=datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc),
                completo=completo,
            )
        )


def test_partite_mostra_prossime_e_ultimo_aggiornamento(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    t = visibile(at)
    assert "Dati aggiornati: 04/11 00:30" in t  # 23:30 UTC = 00:30 a Roma (ora solare)
    assert "Casa FC" in t and "Trasferta FC" in t
    assert "Rossi" in t
    assert "Giornata 7" in t
    assert "Giornata 9" not in t
    assert "Partita calda" in t  # derby nei dati di prova
    assert "ufficiali" in t
    assert not at.warning


def test_avviso_dati_parziali_se_job_incompleto(sessione_db):
    _prepara(sessione_db, completo=False)
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    assert any("parziali" in w.value for w in at.warning)


def test_nessun_aggiornamento_e_nessuna_partita(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(days=20)
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    t = visibile(at)
    assert "Dati non ancora aggiornati" in t
    assert "Nessuna partita" in t


def test_password_richiesta_se_configurata(sessione_db):
    _prepara(sessione_db)
    at = AppTest.from_file(PAGINA_PARTITE, default_timeout=30)
    at.secrets["password"] = "x"
    at.run()
    assert not at.exception
    assert "Casa FC" not in visibile(at)
    assert len(at.text_input) == 1

    at.text_input[0].set_value("sbagliata").run()
    assert "Casa FC" not in visibile(at)
    assert at.error

    at.text_input[0].set_value("x").run()
    assert not at.exception
    assert "Casa FC" in visibile(at)
