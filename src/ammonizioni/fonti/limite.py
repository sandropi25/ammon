"""Limite delle richieste API-Football: tetto giornaliero (con riserva per l'uso
di oggi) e ritmo massimo al minuto. Il contatore giornaliero è nel database."""
from __future__ import annotations

import time
from collections import deque
from datetime import date
from enum import Enum

from sqlalchemy.orm import Session

from ammonizioni.db.modelli import ContatoreRichieste

FINESTRA_SECONDI = 60.0


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
        oggi=date.today,
    ):
        self.sessione = sessione
        self.max_giorno = max_giorno
        self.max_minuto = max_minuto
        self.riserva_oggi = riserva_oggi
        self.orologio = orologio
        self.dormi = dormi
        self.oggi = oggi
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
