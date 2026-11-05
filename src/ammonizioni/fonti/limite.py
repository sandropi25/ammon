"""Limite delle richieste API-Football: tetto giornaliero (con riserva per l'uso
di oggi) e ritmo massimo al minuto. Il contatore giornaliero è nel database."""
from __future__ import annotations

import time
from collections import deque
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy.orm import Session

from ammonizioni.db.modelli import ContatoreRichieste

FINESTRA_SECONDI = 60.0


def oggi_utc() -> date:
    """Giorno del contatore: data UTC (la quota di API-Football si azzera a mezzanotte UTC)."""
    return datetime.now(timezone.utc).date()


class Priorita(Enum):
    OGGI = "oggi"
    STORICO = "storico"


class LimiteSuperato(Exception):
    """Budget giornaliero di richieste esaurito per la priorità richiesta."""


class LimiteRichieste:
    def __init__(
        self,
        sessione: Session,
        max_giorno: int = 100,
        max_minuto: int = 10,
        riserva_oggi: int = 30,
        orologio=time.monotonic,
        dormi=time.sleep,
        oggi=None,
    ):
        self.sessione = sessione
        self.max_giorno = max_giorno
        self.max_minuto = max_minuto
        self.riserva_oggi = riserva_oggi
        self.orologio = orologio
        self.dormi = dormi
        self.oggi = oggi if oggi is not None else oggi_utc
        self._recenti: deque[float] = deque()

    def _tetto(self, priorita: Priorita) -> int:
        if priorita is Priorita.STORICO:
            return self.max_giorno - self.riserva_oggi
        return self.max_giorno

    def _usate(self) -> int:
        riga = self.sessione.get(ContatoreRichieste, self.oggi())
        return riga.usate if riga is not None else 0

    def rimanenti(self, priorita: Priorita) -> int:
        return max(0, self._tetto(priorita) - self._usate())

    def prendi(self, priorita: Priorita) -> None:
        """Riserva una richiesta: solleva LimiteSuperato se il budget del giorno è
        esaurito, altrimenti attende (se serve) il ritmo al minuto e incrementa il contatore."""
        if self.rimanenti(priorita) <= 0:
            raise LimiteSuperato(
                f"Limite giornaliero di richieste raggiunto ({self._tetto(priorita)})"
            )
        self._attendi_ritmo()
        giorno = self.oggi()
        riga = self.sessione.get(ContatoreRichieste, giorno)
        if riga is None:
            riga = ContatoreRichieste(giorno=giorno, usate=0)
            self.sessione.add(riga)
        riga.usate += 1
        self.sessione.commit()

    def _attendi_ritmo(self) -> None:
        adesso = self.orologio()
        self._scarta_vecchie(adesso)
        if len(self._recenti) >= self.max_minuto:
            attesa = self._recenti[0] + FINESTRA_SECONDI - adesso
            if attesa > 0:
                self.dormi(attesa)
            adesso = self.orologio()
            self._scarta_vecchie(adesso)
        self._recenti.append(adesso)

    def _scarta_vecchie(self, adesso: float) -> None:
        while self._recenti and adesso - self._recenti[0] >= FINESTRA_SECONDI:
            self._recenti.popleft()


class LimiteRichiesteLocale(LimiteRichieste):
    """Come `LimiteRichieste`, ma il contatore giornaliero sta in memoria e non nel database.

    La tabella `contatore_richieste` ha una sola riga per giorno, condivisa da ESPN e
    API-Football: contarci anche football-data ne consumerebbe il budget (o viceversa).
    Per football-data conta soprattutto il ritmo al minuto (10), tenuto comunque; il tetto
    giornaliero in memoria è solo una rete di sicurezza e riparte a ogni nuovo processo."""

    def __init__(self, max_giorno: int = 1000, max_minuto: int = 10, **kwargs):
        super().__init__(
            None, max_giorno=max_giorno, max_minuto=max_minuto, riserva_oggi=0, **kwargs
        )
        self._giorno: date | None = None
        self._conteggio = 0

    def _usate(self) -> int:
        return self._conteggio if self._giorno == self.oggi() else 0

    def prendi(self, priorita: Priorita) -> None:
        if self.rimanenti(priorita) <= 0:
            raise LimiteSuperato(
                f"Limite giornaliero di richieste raggiunto ({self._tetto(priorita)})"
            )
        self._attendi_ritmo()
        giorno = self.oggi()
        if self._giorno != giorno:
            self._giorno, self._conteggio = giorno, 0
        self._conteggio += 1


def crea_limite_football_data() -> LimiteRichiesteLocale:
    """Limite per football-data.org (piano gratuito): 10 richieste al minuto, 1000 al giorno."""
    return LimiteRichiesteLocale(max_giorno=1000, max_minuto=10)
