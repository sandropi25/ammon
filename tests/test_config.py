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


def test_chiave_da_db_se_env_vuota(monkeypatch, sessione):
    from ammonizioni.db import repo

    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    assert config.chiave_api(sessione) is None
    repo.scrivi_impostazione(sessione, "chiave_api", "dal-db")
    assert config.chiave_api(sessione) == "dal-db"
    monkeypatch.setenv("API_FOOTBALL_KEY", "da-env")
    assert config.chiave_api(sessione) == "da-env"
