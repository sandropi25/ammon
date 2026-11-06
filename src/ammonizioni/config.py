"""Configurazione di base: competizioni, stagioni, chiave API e database."""
import os

COMPETIZIONI: dict[str, int] = {
    "serie_a": 135,
    "coppa_italia": 137,
    "liga": 140,
    "copa_del_rey": 143,
    "champions": 2,
    "europa": 3,
    "conference": 848,
}

# Campionati nazionali gestiti (la Serie A per prima).
CAMPIONATI: tuple[int, ...] = (135, 140)

# Nome visualizzato di ogni campionato.
NOMI_CAMPIONATI: dict[int, str] = {135: "Serie A", 140: "Liga"}

# Slug ESPN di ogni competizione.
SLUG_ESPN: dict[int, str] = {
    135: "ita.1",
    137: "ita.coppa_italia",
    140: "esp.1",
    143: "esp.copa_del_rey",
    2: "uefa.champions",
    3: "uefa.europa",
    848: "uefa.europa.conf",
}

# Codici football-data.org dei campionati (arbitri).
CODICE_FOOTBALL_DATA: dict[int, str] = {135: "SA", 140: "PD"}

# Coppa nazionale di ogni campionato.
COPPE_NAZIONALI: dict[int, int] = {135: 137, 140: 143}

# Ammonizioni che portano alla squalifica (diffida = una prima della soglia).
# DA VERIFICARE sui regolamenti in vigore.
SOGLIE_DIFFIDA: dict[int, tuple[int, ...]] = {
    135: (4, 9, 13, 16, 19),
    140: (4, 9, 14, 19),
}

SERIE_A = COMPETIZIONI["serie_a"]

# Derby e rivalità vere, per nome di squadra (campionato -> coppie). I nomi si confrontano
# con quelli del database dopo la normalizzazione di `caricamento.arbitri_fd`
# (maiuscole, accenti, "FC", alias): le squadre assenti dal database vengono ignorate.
DERBY_PREDEFINITI: dict[int, tuple[tuple[str, str], ...]] = {
    135: (
        ("Inter", "Milan"),
        ("Roma", "Lazio"),
        ("Juventus", "Torino"),
        ("Genoa", "Sampdoria"),
        ("Juventus", "Inter"),
        ("Napoli", "Roma"),
        ("Fiorentina", "Juventus"),
        ("Juventus", "Napoli"),
        ("Atalanta", "Brescia"),
        ("Verona", "Chievo"),
        ("Lazio", "Napoli"),
    ),
    140: (
        ("Real Madrid", "Barcelona"),
        ("Real Madrid", "Atlético Madrid"),
        ("Barcelona", "Espanyol"),
        ("Sevilla", "Real Betis"),
        ("Athletic Club", "Real Sociedad"),
        ("Valencia", "Levante"),
        ("Celta Vigo", "Deportivo La Coruña"),
        ("Atlético Madrid", "Barcelona"),
        ("Osasuna", "Athletic Club"),
    ),
}

# Campo caldo automatico: nelle partite casalinghe di campionato delle ultime
# CAMPO_CALDO_STAGIONI stagioni (quella della partita compresa) la media di cartellini
# (gialli + rossi, entrambe le squadre) supera di almeno il 20% quella del campionato,
# con almeno CAMPO_CALDO_PARTITE_MINIME partite casalinghe.
CAMPO_CALDO_STAGIONI = 2
CAMPO_CALDO_SOGLIA = 1.20
CAMPO_CALDO_PARTITE_MINIME = 15

# Zone colorate della classifica (pagina Classifica): posizioni da/a di ogni zona europea e
# numero di squadre retrocesse (le ultime). DA VERIFICARE ogni stagione (posti europei
# in più per il ranking UEFA, coppe nazionali).
ZONE_CLASSIFICA: dict[int, tuple[tuple[str, int, int], ...]] = {
    135: (("champions", 1, 4), ("europa", 5, 6), ("conference", 7, 7)),
    140: (("champions", 1, 4), ("europa", 5, 6), ("conference", 7, 7)),
}
RETROCESSE: dict[int, int] = {135: 3, 140: 3}

# Partita calda: cartellini attesi (gialli + rossi) pari o sopra questa soglia, oppure derby.
SOGLIA_CARTELLINI_ATTESI = 5.5


def campionato_di(competizione_id: int) -> int | None:
    """Il campionato a cui appartiene una competizione: il campionato stesso, la sua coppa
    nazionale (Coppa Italia -> Serie A, Copa del Rey -> Liga); None per le coppe europee,
    che non appartengono a un campionato."""
    if competizione_id in CAMPIONATI:
        return competizione_id
    for campionato, coppa in COPPE_NAZIONALI.items():
        if coppa == competizione_id:
            return campionato
    return None


FONTI_DATI = ("espn", "api_football")

STAGIONE_CORRENTE = 2026
STAGIONI = (2026, 2025, 2024)

# Stati API-Football di una partita finita: tempi regolamentari, supplementari, rigori.
STATI_FINITI = ("FT", "AET", "PEN")

URL_API = "https://v3.football.api-sports.io"


def fonte_dati() -> str:
    """Fonte dati scelta con la variabile d'ambiente FONTE_DATI: "espn" (predefinita)
    o "api_football"."""
    valore = os.environ.get("FONTE_DATI") or "espn"
    if valore not in FONTI_DATI:
        raise ValueError(
            f"FONTE_DATI={valore!r} sconosciuta: valori ammessi {' o '.join(FONTI_DATI)}"
        )
    return valore


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


def chiave_football_data(sessione=None) -> str | None:
    """Chiave football-data.org: prima la variabile d'ambiente FOOTBALL_DATA_KEY,
    poi (se data una sessione) l'impostazione 'chiave_football_data' nel database."""
    valore = os.environ.get("FOOTBALL_DATA_KEY")
    if valore:
        return valore
    if sessione is not None:
        from ammonizioni.db import repo  # import locale: evita import circolari

        return repo.leggi_impostazione(sessione, "chiave_football_data", None) or None
    return None


def url_database() -> str:
    """URL del database. Gli URL Postgres di Supabase (`postgres://` o `postgresql://`)
    vengono portati a `postgresql+psycopg://`, il driver psycopg 3 usato da SQLAlchemy."""
    url = os.environ.get("DATABASE_URL") or "sqlite:///ammonizioni.db"
    for prefisso in ("postgres://", "postgresql://"):
        if url.startswith(prefisso):
            return "postgresql+psycopg://" + url[len(prefisso):]
    return url
