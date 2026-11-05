from datetime import datetime, timedelta, timezone

from ayuda_app import PAGINA_PARTITE, avvia, sessione_db, url_db, visibile
from db_prova import PARTITA_FUTURA, popola
import pytest
from streamlit.errors import StreamlitSecretNotFoundError
from streamlit.testing.v1 import AppTest

from ammonizioni.db.modelli import Arbitro, Partita, Squadra, UltimoAggiornamento


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


LIGA_PARTITA = 900


def _aggiungi_liga(sessione_db):
    """Una partita di Liga tra 3 giorni, con squadre e arbitro propri."""
    with sessione_db() as s:
        s.add_all([Squadra(id=501, nome="Real Liga"), Squadra(id=502, nome="Barca Liga")])
        s.add(Arbitro(id=60, nome_normalizzato="manzano", nome_visualizzato="Gil Manzano"))
        s.flush()
        s.add(
            Partita(
                id=LIGA_PARTITA, data_utc=datetime.now(timezone.utc) + timedelta(days=3),
                competizione_id=140, stagione=2026, giornata=11, casa_id=501, trasferta_id=502,
                arbitro_id=60, stato="NS",
            )
        )


def test_filtro_campionato_predefinito_serie_a(sessione_db):
    _prepara(sessione_db)
    _aggiungi_liga(sessione_db)
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    assert at.radio(key="filtro_partite").value == "Serie A"
    assert list(at.radio(key="filtro_partite").options) == ["Serie A", "Liga", "Tutti"]
    t = visibile(at)
    assert "Casa FC" in t and "Real Liga" not in t


def test_filtro_campionato_liga_e_tutti(sessione_db):
    _prepara(sessione_db)
    _aggiungi_liga(sessione_db)
    at = avvia(PAGINA_PARTITE)

    at.radio(key="filtro_partite").set_value("Liga").run()
    assert not at.exception
    t = visibile(at)
    assert "Real Liga – Barca Liga" in t and "Gil Manzano" in t and "Giornata 11" in t
    assert "Casa FC" not in t

    at.radio(key="filtro_partite").set_value("Tutti").run()
    t = visibile(at)
    assert "Real Liga" in t and "Casa FC" in t
    # ogni partita dice il suo campionato
    assert "Liga" in t and "Serie A" in t


def test_filtro_liga_senza_partite(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_PARTITE)
    at.radio(key="filtro_partite").set_value("Liga").run()
    assert not at.exception
    assert "Nessuna partita di Liga nei prossimi 7 giorni" in visibile(at)
    assert "Casa FC" not in visibile(at)


def test_prossime_partite_funzione_predefinito_serie_a(sessione_db):
    import componenti

    _prepara(sessione_db)
    _aggiungi_liga(sessione_db)
    ora = datetime.now(timezone.utc)
    with sessione_db() as s:
        assert [p.casa for p in componenti.prossime_partite(s, ora)] == ["Casa FC"]
        assert [p.casa for p in componenti.prossime_partite(s, ora, campionati=(140,))] == ["Real Liga"]
        tutte = componenti.prossime_partite(s, ora, campionati=componenti.CAMPIONATI)
        assert [(p.casa, p.campionato) for p in tutte] == [
            ("Casa FC", "Serie A"), ("Real Liga", "Liga"),
        ]


def test_partita_di_liga_non_e_calda_per_il_derby_di_serie_a(sessione_db):
    """Il derby del seed e' fra squadre di Serie A: la partita di Liga non e' "calda"."""
    _prepara(sessione_db)
    _aggiungi_liga(sessione_db)
    at = avvia(PAGINA_PARTITE)
    at.radio(key="filtro_partite").set_value("Liga").run()
    assert "Partita calda" not in visibile(at)


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


def _avvia_con_secrets_rotti(tmp_path, monkeypatch):
    cartella = tmp_path / ".streamlit"
    cartella.mkdir()
    (cartella / "secrets.toml").write_text('password = "x\n', encoding="utf-8")  # TOML non valido
    monkeypatch.chdir(tmp_path)
    return AppTest.from_file(PAGINA_PARTITE, default_timeout=30).run()


def test_secrets_illeggibili_bloccano_l_app(sessione_db, tmp_path, monkeypatch):
    _prepara(sessione_db)
    at = _avvia_con_secrets_rotti(tmp_path, monkeypatch)
    assert not at.exception
    assert any("configurazione della password" in e.value for e in at.error)
    assert "Casa FC" not in visibile(at)


def _errore_permesso(*_):
    return PermissionError("negato")


def _errore_percorso_non_valido(*_):
    # stessa classe di "nessun segreto", ma errore_id diverso
    return StreamlitSecretNotFoundError("Invalid secrets path: {p}", p="x", error_id="invalid-secrets-path")


def _errore_senza_id(*_):
    return StreamlitSecretNotFoundError("Messaggio riformulato da una nuova versione")


@pytest.mark.parametrize(
    "costruisci", [_errore_permesso, _errore_percorso_non_valido, _errore_senza_id]
)
def test_errore_imprevisto_nei_segreti_blocca_l_app(sessione_db, monkeypatch, costruisci):
    from streamlit.runtime.secrets import Secrets

    def guasto(self, *args, **kwargs):
        raise costruisci()

    monkeypatch.setattr(Secrets, "get", guasto)
    _prepara(sessione_db)
    at = AppTest.from_file(PAGINA_PARTITE, default_timeout=30).run()
    assert not at.exception
    assert any("configurazione della password" in e.value for e in at.error)
    assert "Casa FC" not in visibile(at)
