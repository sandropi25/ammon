from ammonizioni import config


def test_chiave_da_env(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "abc")
    assert config.chiave_api() == "abc"


def test_url_database_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.url_database() == "sqlite:///ammonizioni.db"


def test_stagioni():
    assert config.STAGIONI == (2026, 2025, 2024)


def test_chiave_da_db_se_env_vuota(monkeypatch, sessione):
    from ammonizioni.db import repo

    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    assert config.chiave_api(sessione) is None
    repo.scrivi_impostazione(sessione, "chiave_api", "dal-db")
    assert config.chiave_api(sessione) == "dal-db"
    monkeypatch.setenv("API_FOOTBALL_KEY", "da-env")
    assert config.chiave_api(sessione) == "da-env"
