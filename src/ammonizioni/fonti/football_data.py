"""Fonte football-data.org (piano gratuito, chiave in FOOTBALL_DATA_KEY): serve solo
per gli arbitri, che ESPN non fornisce. Una chiamata restituisce un'intera stagione
(380 partite) oppure un intervallo di date; il piano gratuito concede 10 richieste al minuto."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.limite import LimiteRichieste, Priorita

log = logging.getLogger(__name__)

URL_FOOTBALL_DATA = "https://api.football-data.org/v4"
TENTATIVI = 5  # primo tentativo + 4 retry
ATTESE_RETRY = (1, 2, 4, 8)
TIMEOUT_SECONDI = 60.0
GIORNI_PER_CHIAMATA = 10  # intervallo massimo di dateFrom/dateTo documentato dall'API


@dataclass(frozen=True)
class ArbitroPartita:
    data_utc: datetime  # aware UTC
    casa: str
    trasferta: str
    arbitro_id: int | None  # id football-data
    arbitro_nome: str | None  # None se l'arbitro non è ancora designato


def stagione_intera(dal: date, al: date) -> int | None:
    """Stagione S se l'intervallo è proprio la stagione (dal 1° luglio S al 30 giugno S+1,
    con un giorno di tolleranza alla fine), altrimenti None. Un intervallo più largo non
    conta: una chiamata `season=` perderebbe le partite fuori stagione."""
    if dal.month == 7 and dal.day == 1 and date(dal.year + 1, 6, 30) <= al <= date(dal.year + 1, 7, 1):
        return dal.year
    return None


class FootballData:
    def __init__(
        self,
        chiave: str | None,
        limite: LimiteRichieste | None = None,
        client: httpx.Client | None = None,
        dormi=time.sleep,
    ):
        self.chiave = chiave
        self.limite = limite
        self.client = client if client is not None else httpx.Client(timeout=TIMEOUT_SECONDI)
        self.dormi = dormi

    def arbitri(self, codice: str, dal: date, al: date) -> list[ArbitroPartita]:
        """Partite del campionato `codice` (es. "SA") nell'intervallo [dal, al] con il loro
        arbitro. Una sola richiesta se l'intervallo copre una stagione intera (`season=`),
        altrimenti una per ogni blocco di 10 giorni (`dateFrom`/`dateTo`)."""
        percorso = f"/competitions/{codice}/matches"
        stagione = stagione_intera(dal, al)
        if stagione is not None:
            richieste = [{"season": stagione}]
        else:
            richieste = []
            inizio = dal
            while inizio <= al:
                fine = min(inizio + timedelta(days=GIORNI_PER_CHIAMATA - 1), al)
                richieste.append({"dateFrom": inizio.isoformat(), "dateTo": fine.isoformat()})
                inizio = fine + timedelta(days=1)
        risultato: list[ArbitroPartita] = []
        for parametri in richieste:
            corpo = self._get(percorso, parametri)
            partite = corpo.get("matches")
            if not isinstance(partite, list):
                raise ErroreFonte(
                    f"Risposta football-data senza 'matches' per {codice} {parametri}: "
                    "struttura cambiata?"
                )
            for partita in partite:
                letta = self._partita(partita)
                if letta is not None:
                    risultato.append(letta)
        return risultato

    @staticmethod
    def _partita(partita) -> ArbitroPartita | None:
        try:
            data = datetime.fromisoformat(partita["utcDate"].replace("Z", "+00:00"))
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
            casa = partita["homeTeam"]["name"]
            trasferta = partita["awayTeam"]["name"]
        except (KeyError, TypeError, ValueError, AttributeError):
            log.warning("Partita football-data non letta: %s", partita)
            return None
        if not casa or not trasferta:  # squadre ancora da definire
            return None
        arbitro_id, arbitro_nome = None, None
        for r in partita.get("referees") or []:
            if isinstance(r, dict) and r.get("type") == "REFEREE" and r.get("name"):
                arbitro_id = r.get("id")
                arbitro_nome = r["name"]
                break
        return ArbitroPartita(
            data_utc=data.astimezone(timezone.utc),
            casa=casa,
            trasferta=trasferta,
            arbitro_id=arbitro_id,
            arbitro_nome=arbitro_nome,
        )

    def _get(self, percorso: str, parametri: dict) -> dict:
        ultimo_errore = "errore sconosciuto"
        for tentativo in range(TENTATIVI):
            if tentativo > 0:
                self.dormi(ATTESE_RETRY[tentativo - 1])
            # prima della chiamata: se il budget è finito non si fa nessuna richiesta
            if self.limite is not None:
                self.limite.prendi(Priorita.OGGI)
            try:
                risposta = self.client.get(
                    URL_FOOTBALL_DATA + percorso,
                    params=parametri,
                    headers={"X-Auth-Token": self.chiave or ""},
                )
            except httpx.TransportError as e:
                ultimo_errore = f"errore di rete: {e}"
                continue
            if risposta.status_code == 429 or risposta.status_code >= 500:
                ultimo_errore = f"HTTP {risposta.status_code}"
                continue
            if risposta.status_code in (400, 401, 403, 404):
                raise ErroreFonte(
                    f"football-data HTTP {risposta.status_code} su {percorso} {parametri}: "
                    "chiave non valida o competizione/stagione non disponibile nel piano gratuito"
                )
            if risposta.status_code != 200:
                raise ErroreFonte(f"HTTP {risposta.status_code} su {percorso}")
            try:
                corpo = risposta.json()
            except ValueError as e:
                raise ErroreFonte(f"Risposta non valida su {percorso}: {e}") from e
            if not isinstance(corpo, dict):
                raise ErroreFonte(f"Risposta non valida su {percorso}: non è un oggetto JSON")
            return corpo
        raise ErroreFonte(f"{percorso}: {TENTATIVI} tentativi falliti ({ultimo_errore})")
