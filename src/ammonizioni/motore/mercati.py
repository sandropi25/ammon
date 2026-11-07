from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from ammonizioni.motore import modello
from ammonizioni.motore.classifica import classifica
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.pesi import carica_pesi
from ammonizioni.motore.tipi import Candidato, Titolare


class Mercato(Protocol):
    nome: str

    def classifica(
        self,
        s: Session,
        partita_id: int,
        quote: dict[int, float] | None = None,
        prima_di: datetime | None = None,
        titolari: list[Titolare] | None = None,
    ) -> list[Candidato]: ...


class MercatoAmmonizioni:
    nome = "ammonizioni"

    def classifica(
        self,
        s: Session,
        partita_id: int,
        quote: dict[int, float] | None = None,
        prima_di: datetime | None = None,
        titolari: list[Titolare] | None = None,
    ) -> list[Candidato]:
        scelto = modello.modello_scelto(s)
        if scelto != modello.V2:
            dati = carica_dati(s, partita_id, prima_di=prima_di, titolari=titolari)
            return classifica(dati, carica_pesi(s), quote)
        # V2 divide i cartellini attesi su tutta la distinta: serve anche la panchina
        dati = carica_dati(s, partita_id, prima_di=prima_di, titolari=titolari, con_panchina=True)
        pesi = carica_pesi(s)
        return modello.applica_v2(
            dati, pesi, modello.carica_coefficienti(s), classifica(dati, pesi, quote), []
        )[0]
