from ammonizioni import config


def test_chiave_da_env(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "abc")
    assert config.chiave_api() == "abc"


def test_url_database_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.url_database() == "sqlite:///ammonizioni.db"


def test_stagioni():
    assert config.STAGIONI == (2026, 2025, 2024)
