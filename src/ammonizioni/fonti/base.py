"""Interfaccia comune delle fonti dati."""
from __future__ import annotations

from typing import Protocol

from ammonizioni.fonti.tipi import FormazioneDati, PartitaDati, PresenzaDati


class ErroreFonte(Exception):
    """Errore non recuperabile nella lettura da una fonte dati."""


class Fonte(Protocol):
    def partite(self, competizione_id: int, stagione: int) -> list[PartitaDati]: ...

    def partita(self, id: int) -> PartitaDati: ...

    def statistiche(self, partita_id: int) -> list[PresenzaDati]: ...

    def formazioni(self, partita_id: int) -> list[FormazioneDati]:
        """Lista vuota se le formazioni non sono ancora uscite."""
        ...
