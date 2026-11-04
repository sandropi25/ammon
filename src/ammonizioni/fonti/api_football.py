"""Client API-Football v3 con limite richieste e retry."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import httpx

from ammonizioni.config import URL_API
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.limite import LimiteRichieste, Priorita
from ammonizioni.fonti.tipi import FormazioneDati, PartitaDati, PresenzaDati

TENTATIVI = 5  # primo tentativo + 4 retry
ATTESE_RETRY = (1, 2, 4, 8)
TIMEOUT_SECONDI = 30.0


def _int(valore) -> int:
    return int(valore) if valore is not None else 0


def _voto(valore) -> float | None:
    if valore is None or valore == "":
        return None
    try:
        return float(valore)
    except (TypeError, ValueError):
        return None


def _giornata(testo: str | None) -> int | None:
    if not testo:
        return None
    trovato = re.search(r"-\s*(\d+)\s*$", testo)
    return int(trovato.group(1)) if trovato else None


class ApiFootball:
    def __init__(
        self,
        chiave: str,
        limite: LimiteRichieste,
        client: httpx.Client | None = None,
        priorita: Priorita = Priorita.OGGI,
        dormi=time.sleep,
    ):
        self.chiave = chiave
        self.limite = limite
        self.client = client if client is not None else httpx.Client(timeout=TIMEOUT_SECONDI)
        self.priorita = priorita
        self.dormi = dormi

    # --- Fonte ---------------------------------------------------------

    def partite(self, competizione_id: int, stagione: int) -> list[PartitaDati]:
        risposta = self._get("/fixtures", {"league": competizione_id, "season": stagione})
        return [self._partita(r) for r in risposta]

    def partita(self, id: int) -> PartitaDati:
        risposta = self._get("/fixtures", {"id": id})
        if not risposta:
            raise ErroreFonte(f"Partita {id} non trovata")
        return self._partita(risposta[0])

    def statistiche(self, partita_id: int) -> list[PresenzaDati]:
        risposta = self._get("/fixtures/players", {"fixture": partita_id})
        presenze: list[PresenzaDati] = []
        for squadra in risposta:
            squadra_id = squadra["team"]["id"]
            for giocatore in squadra.get("players") or []:
                statistiche = giocatore.get("statistics") or []
                if not statistiche:
                    continue
                s = statistiche[0]
                games = s.get("games") or {}
                cards = s.get("cards") or {}
                fouls = s.get("fouls") or {}
                dribbles = s.get("dribbles") or {}
                goals = s.get("goals") or {}
                shots = s.get("shots") or {}
                presenze.append(
                    PresenzaDati(
                        partita_id=partita_id,
                        giocatore_id=giocatore["player"]["id"],
                        giocatore_nome=giocatore["player"]["name"],
                        squadra_id=squadra_id,
                        titolare=not games.get("substitute"),
                        ruolo=games.get("position"),
                        griglia=None,  # arriva dalle formazioni
                        minuti=_int(games.get("minutes")),
                        gialli=_int(cards.get("yellow")),
                        rossi=_int(cards.get("red")),
                        falli_commessi=_int(fouls.get("committed")),
                        falli_subiti=_int(fouls.get("drawn")),
                        dribbling_tentati=_int(dribbles.get("attempts")),
                        dribbling_riusciti=_int(dribbles.get("success")),
                        tiri=_int(shots.get("total")),
                        gol=_int(goals.get("total")),
                        assist=_int(goals.get("assists")),
                        voto=_voto(games.get("rating")),
                    )
                )
        return presenze

    def formazioni(self, partita_id: int) -> list[FormazioneDati]:
        risposta = self._get("/fixtures/lineups", {"fixture": partita_id})
        formazioni = []
        for squadra in risposta:
            titolari = []
            for voce in squadra.get("startXI") or []:
                g = voce["player"]
                titolari.append((g["id"], g["name"], g.get("pos"), g.get("grid")))
            formazioni.append(
                FormazioneDati(
                    partita_id=partita_id,
                    squadra_id=squadra["team"]["id"],
                    titolari=titolari,
                )
            )
        return formazioni

    # --- conversioni ---------------------------------------------------

    @staticmethod
    def _partita(r: dict) -> PartitaDati:
        fixture = r["fixture"]
        data = datetime.fromisoformat(fixture["date"])
        if data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)
        goals = r.get("goals") or {}
        return PartitaDati(
            id=fixture["id"],
            data_utc=data.astimezone(timezone.utc),
            competizione_id=r["league"]["id"],
            stagione=r["league"]["season"],
            giornata=_giornata(r["league"].get("round")),
            casa_id=r["teams"]["home"]["id"],
            casa_nome=r["teams"]["home"]["name"],
            trasferta_id=r["teams"]["away"]["id"],
            trasferta_nome=r["teams"]["away"]["name"],
            arbitro_nome=fixture.get("referee") or None,
            gol_casa=goals.get("home"),
            gol_trasferta=goals.get("away"),
            stato=fixture["status"]["short"],
        )

    # --- HTTP con limite e retry ---------------------------------------

    def _get(self, percorso: str, parametri: dict) -> list:
        ultimo_errore = "errore sconosciuto"
        for tentativo in range(TENTATIVI):
            if tentativo > 0:
                self.dormi(ATTESE_RETRY[tentativo - 1])
            # prima della chiamata: se il budget è finito non si fa nessuna richiesta
            self.limite.prendi(self.priorita)
            try:
                risposta = self.client.get(
                    URL_API + percorso,
                    params=parametri,
                    headers={"x-apisports-key": self.chiave},
                )
            except httpx.TransportError as e:
                ultimo_errore = f"errore di rete: {e}"
                continue
            if risposta.status_code == 429 or risposta.status_code >= 500:
                ultimo_errore = f"HTTP {risposta.status_code}"
                continue
            if risposta.status_code != 200:
                raise ErroreFonte(f"HTTP {risposta.status_code} su {percorso}")
            try:
                corpo = risposta.json()
            except ValueError as e:
                raise ErroreFonte(f"Risposta non valida su {percorso}: {e}") from e
            errori = corpo.get("errors")
            if errori:
                if isinstance(errori, dict):
                    errori = list(errori.values())
                elif not isinstance(errori, list):
                    errori = [errori]
                raise ErroreFonte("; ".join(str(e) for e in errori))
            return corpo.get("response") or []
        raise ErroreFonte(f"{percorso}: {TENTATIVI} tentativi falliti ({ultimo_errore})")
