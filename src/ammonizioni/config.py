"""Configurazione di base: competizioni, stagioni, chiave API e database."""
import os

COMPETIZIONI: dict[str, int] = {
    "serie_a": 135,
    "coppa_italia": 137,
    "champions": 2,
    "europa": 3,
    "conference": 848,
}

STAGIONE_CORRENTE = 2026
STAGIONI = (2026, 2025, 2024)

URL_API = "https://v3.football.api-sports.io"


def chiave_api(sessione=None) -> str | None:
    """Chiave API-Football letta dalla variabile d'ambiente API_FOOTBALL_KEY."""
    valore = os.environ.get("API_FOOTBALL_KEY")
    return valore or None


def url_database() -> str:
    return os.environ.get("DATABASE_URL") or "sqlite:///ammonizioni.db"
