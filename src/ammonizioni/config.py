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
    """Chiave API-Football: prima la variabile d'ambiente API_FOOTBALL_KEY,
    poi (se data una sessione) l'impostazione 'chiave_api' nel database."""
    valore = os.environ.get("API_FOOTBALL_KEY")
    if valore:
        return valore
    if sessione is not None:
        from ammonizioni.db import repo  # import locale: evita import circolari

        return repo.leggi_impostazione(sessione, "chiave_api", None) or None
    return None


def url_database() -> str:
    return os.environ.get("DATABASE_URL") or "sqlite:///ammonizioni.db"
