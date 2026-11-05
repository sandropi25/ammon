import pytest

from ammonizioni import config


def test_chiave_da_env(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "abc")
    assert config.chiave_api() == "abc"


def test_url_database_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.url_database() == "sqlite:///ammonizioni.db"


@pytest.mark.parametrize(
    "ricevuto, atteso",
    [
        ("postgresql://u:p@host:5432/postgres", "postgresql+psycopg://u:p@host:5432/postgres"),
        ("postgres://u:p@host:6543/postgres", "postgresql+psycopg://u:p@host:6543/postgres"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///altro.db", "sqlite:///altro.db"),
    ],
)
def test_url_database_normalizza_postgres(monkeypatch, ricevuto, atteso):
    monkeypatch.setenv("DATABASE_URL", ricevuto)
    assert config.url_database() == atteso


def test_stagioni():
    assert config.STAGIONI == (2026, 2025, 2024)


def test_stati_finiti_comprendono_supplementari_e_rigori():
    assert config.STATI_FINITI == ("FT", "AET", "PEN")


def test_competizioni_sette_voci_con_id_invariati():
    assert config.COMPETIZIONI == {
        "serie_a": 135,
        "coppa_italia": 137,
        "liga": 140,
        "copa_del_rey": 143,
        "champions": 2,
        "europa": 3,
        "conference": 848,
    }


def test_campionati():
    assert config.CAMPIONATI == (135, 140)


@pytest.mark.parametrize(
    "competizione_id, slug",
    [
        (135, "ita.1"),
        (137, "ita.coppa_italia"),
        (140, "esp.1"),
        (143, "esp.copa_del_rey"),
        (2, "uefa.champions"),
        (3, "uefa.europa"),
        (848, "uefa.europa.conf"),
    ],
)
def test_slug_espn(competizione_id, slug):
    assert config.SLUG_ESPN[competizione_id] == slug


def test_slug_espn_copre_tutte_le_competizioni():
    assert set(config.SLUG_ESPN) == set(config.COMPETIZIONI.values())


def test_codici_football_data_coppe_e_soglie():
    assert config.CODICE_FOOTBALL_DATA == {135: "SA", 140: "PD"}
    assert config.COPPE_NAZIONALI == {135: 137, 140: 143}
    assert config.SOGLIE_DIFFIDA == {135: (4, 9, 13, 16, 19), 140: (4, 9, 14, 19)}


def test_fonte_dati_predefinita_espn(monkeypatch):
    monkeypatch.delenv("FONTE_DATI", raising=False)
    assert config.fonte_dati() == "espn"


@pytest.mark.parametrize("valore", ["espn", "api_football"])
def test_fonte_dati_da_env(monkeypatch, valore):
    monkeypatch.setenv("FONTE_DATI", valore)
    assert config.fonte_dati() == valore


def test_fonte_dati_sconosciuta_errore_chiaro(monkeypatch):
    monkeypatch.setenv("FONTE_DATI", "sofascore")
    with pytest.raises(ValueError, match="FONTE_DATI.*sofascore.*espn.*api_football"):
        config.fonte_dati()


def test_chiave_da_db_se_env_vuota(monkeypatch, sessione):
    from ammonizioni.db import repo

    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    assert config.chiave_api(sessione) is None
    repo.scrivi_impostazione(sessione, "chiave_api", "dal-db")
    assert config.chiave_api(sessione) == "dal-db"
    monkeypatch.setenv("API_FOOTBALL_KEY", "da-env")
    assert config.chiave_api(sessione) == "da-env"
