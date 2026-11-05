"""Collega gli arbitri di football-data.org (nome di ogni partita) alle partite del database,
che arrivano da ESPN senza arbitro. Il collegamento è per data (±3 ore) e per squadre
(casa con casa, trasferta con trasferta): mai su una squadra sola."""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.arbitri import trova_o_crea
from ammonizioni.config import CAMPIONATI, CODICE_FOOTBALL_DATA
from ammonizioni.db.modelli import Partita, Squadra
from ammonizioni.fonti.football_data import ArbitroPartita, FootballData

log = logging.getLogger(__name__)

TOLLERANZA = timedelta(hours=3)

# Parole che non distinguono una squadra: sigle societarie e articoli ("FC", "SSC", "Calcio",
# "Club", "de"...). Gli anni (1909, 1913, 1907) sono tolti a parte.
_PAROLE_VUOTE = frozenset(
    {
        "fc", "ac", "acf", "ssc", "ss", "as", "us", "cf", "cfc", "bc", "sc", "afc", "rc", "rcd",
        "ca", "ud", "cd", "calcio", "club", "futbol", "balompie", "de", "di", "del", "la",
    }
)

# Nome già normalizzato (football-data o altre fonti) -> nome normalizzato usato da ESPN.
# Costruita dai nomi reali di Serie A 2024-2026 e Liga 2026 (vedi tests/caricamento/test_arbitri_fd.py).
ALIAS_SQUADRE: dict[str, str] = {
    # Serie A
    "internazionale milano": "internazionale",  # FC Internazionale Milano
    "inter": "internazionale",
    "inter milan": "internazionale",
    "verona": "hellas verona",
    # Liga
    "espanyol barcelona": "espanyol",  # RCD Espanyol de Barcelona
    "rayo vallecano madrid": "rayo vallecano",  # Rayo Vallecano de Madrid
    "deportivo alaves": "alaves",
    "deportivo coruna": "deportivo",  # RC Deportivo La Coruña
    "real racing santander": "racing santander",  # Real Racing Club de Santander
    "athletic bilbao": "athletic",
}


def _senza_accenti(testo: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", testo) if not unicodedata.combining(c))


def nome_squadra_normalizzato(nome: str) -> str:
    """Minuscolo, senza accenti, senza sigle ("FC", "AC", "SSC"...), senza "Calcio"/"Club"
    e senza anno di fondazione, poi la tabella `ALIAS_SQUADRE`."""
    parole = re.sub(r"[^a-z0-9]+", " ", _senza_accenti(nome).lower()).split()
    parole = [p for p in parole if p not in _PAROLE_VUOTE and not re.fullmatch(r"\d{4}", p)]
    normalizzato = " ".join(parole)
    return ALIAS_SQUADRE.get(normalizzato, normalizzato)


def stessa_squadra(a: str, b: str) -> bool:
    chiave = nome_squadra_normalizzato(a)
    return bool(chiave) and chiave == nome_squadra_normalizzato(b)


def _stagione_di(data: datetime) -> int:
    """Stagione (anno d'inizio) di una data: dal 1 luglio al 30 giugno."""
    return data.year if data.month >= 7 else data.year - 1


def collega(
    s: Session, fonte_fd: FootballData, competizione_id: int, dal: date, al: date
) -> int:
    """Assegna l'arbitro alle partite del database senza arbitro e il numero di giornata a
    quelle senza giornata (campo `matchday` di football-data, mai sovrascritto se già
    presente), tra le date `dal` e `al` (comprese), per la competizione data. Una sola lettura
    di football-data (una richiesta se l'intervallo è una stagione intera); se tutte le
    partite hanno già arbitro e giornata non fa nessuna richiesta. Restituisce i
    collegamenti di arbitri fatti; le partite non collegate restano senza arbitro (fattore
    arbitro neutro) e sono scritte nel log.
    Senza chiave non fa nulla. Gli errori della fonte (ErroreFonte, LimiteSuperato) salgono."""
    if not getattr(fonte_fd, "chiave", None):
        log.warning(
            "Chiave football-data.org mancante (variabile FOOTBALL_DATA_KEY): "
            "arbitri non collegati"
        )
        return 0
    codice = CODICE_FOOTBALL_DATA.get(competizione_id)
    if codice is None:
        log.warning("Competizione %s senza codice football-data.org: arbitri non collegati",
                    competizione_id)
        return 0
    inizio = datetime.combine(dal, time.min, tzinfo=timezone.utc)
    fine = datetime.combine(al + timedelta(days=1), time.min, tzinfo=timezone.utc)
    partite = s.scalars(
        select(Partita)
        .where(
            Partita.competizione_id == competizione_id,
            Partita.arbitro_id.is_(None) | Partita.giornata.is_(None),
            Partita.data_utc >= inizio,
            Partita.data_utc < fine,
        )
        .order_by(Partita.data_utc, Partita.id)
    ).all()
    if not partite:
        return 0

    per_squadre: dict[tuple[str, str], list[ArbitroPartita]] = {}
    for voce in fonte_fd.arbitri(codice, dal, al):
        chiave = (nome_squadra_normalizzato(voce.casa), nome_squadra_normalizzato(voce.trasferta))
        per_squadre.setdefault(chiave, []).append(voce)

    collegate = 0
    for partita in partite:
        casa = s.get(Squadra, partita.casa_id)
        trasferta = s.get(Squadra, partita.trasferta_id)
        candidate = per_squadre.get(
            (nome_squadra_normalizzato(casa.nome), nome_squadra_normalizzato(trasferta.nome)), []
        )
        vicine = [v for v in candidate if abs(v.data_utc - partita.data_utc) <= TOLLERANZA]
        if not vicine:
            # Solo la giornata, mai l'arbitro: ESPN da' per le partite lontane una data
            # provvisoria, ma nel campionato una coppia casa-trasferta c'e' una volta sola
            # a stagione.
            if competizione_id in CAMPIONATI and partita.giornata is None:
                stessa_stagione = [
                    v for v in candidate if _stagione_di(v.data_utc) == partita.stagione
                ]
                if len(stessa_stagione) == 1 and stessa_stagione[0].giornata is not None:
                    partita.giornata = stessa_stagione[0].giornata
                    log.info(
                        "Partita %s (%s - %s): giornata %s dalla coppia di squadre "
                        "(data provvisoria), arbitro non assegnato",
                        partita.id, casa.nome, trasferta.nome, partita.giornata,
                    )
                    continue
            log.warning(
                "Partita %s (%s - %s, %s): nessuna corrispondenza su football-data.org, "
                "arbitro e giornata non assegnati",
                partita.id, casa.nome, trasferta.nome, partita.data_utc.isoformat(),
            )
            continue
        voce = min(vicine, key=lambda v: abs(v.data_utc - partita.data_utc))
        # la giornata arriva solo da qui (ESPN non la da'): mai sovrascritta se gia' presente
        if partita.giornata is None and voce.giornata is not None:
            partita.giornata = voce.giornata
        if partita.arbitro_id is not None:
            continue
        arbitro = trova_o_crea(s, voce.arbitro_nome, competizione_id)
        if arbitro is None:
            log.info(
                "Partita %s (%s - %s): arbitro non ancora designato su football-data.org",
                partita.id, casa.nome, trasferta.nome,
            )
            continue
        partita.arbitro_id = arbitro.id
        collegate += 1
    s.commit()
    return collegate
