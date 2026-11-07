from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.limite import LimiteSuperato
from ammonizioni.fonti.tipi import FormazioneDati, PartitaDati, PresenzaDati


@pytest.fixture(autouse=True)
def _chiudi_engines_in_cache():
    """Gli engine aperti da `apri()` restano in cache per URL: chiusi dopo ogni test."""
    yield
    modulo_sessione.chiudi_engines()


@pytest.fixture(autouse=True)
def _niente_rete_per_le_designazioni(monkeypatch):
    """I job chiamano l'AIA: nei test la rete non si tocca (risposta 503, nessuna designazione)."""
    from ammonizioni.caricamento import designazioni

    monkeypatch.setattr(
        designazioni,
        "crea_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
    )


@pytest.fixture
def sessione():
    engine = modulo_sessione.crea_engine("sqlite://")
    modulo_sessione.crea_tabelle(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def partita_dati(
    id: int,
    data_utc: datetime,
    *,
    competizione_id: int = 135,
    stagione: int = 2026,
    casa: tuple[int, str] = (1, "Juventus"),
    trasferta: tuple[int, str] = (2, "Inter"),
    stato: str = "FT",
    arbitro: str | None = "Daniele Doveri, Italy",
    giornata: int | None = 1,
) -> PartitaDati:
    return PartitaDati(
        id=id,
        data_utc=data_utc,
        competizione_id=competizione_id,
        stagione=stagione,
        giornata=giornata,
        casa_id=casa[0],
        casa_nome=casa[1],
        trasferta_id=trasferta[0],
        trasferta_nome=trasferta[1],
        arbitro_nome=arbitro,
        gol_casa=1 if stato == "FT" else None,
        gol_trasferta=0 if stato == "FT" else None,
        stato=stato,
    )


class FonteFinta:
    """Fonte in memoria: conta le chiamate (`chiamate`), può sollevare LimiteSuperato
    dopo `limite_dopo` chiamate riuscite e ErroreFonte per gli id in `errori`.

    Senza `calendari`, `partite(135, 2026)` restituisce `partite_ft` partite FT
    (id 1..N, la più recente è quella con id più alto) e le altre combinazioni nessuna.
    """

    def __init__(
        self,
        partite_ft=0,
        limite_dopo=None,
        errori=(),
        calendari=None,
        formazioni_uscite=None,
        errori_formazioni=(),
        statistiche_vuote=(),
        due_squadre=False,
    ):
        # True: `statistiche` restituisce anche un attaccante della squadra in trasferta
        self.due_squadre = due_squadre
        self.limite_dopo = limite_dopo
        self.errori = set(errori)
        # partite per cui `statistiche` risponde con una lista vuota
        self.statistiche_vuote = set(statistiche_vuote)
        # partita_id -> formazioni restituite da `formazioni` (assenti = non ancora uscite)
        self.formazioni_uscite = formazioni_uscite or {}
        self.errori_formazioni = set(errori_formazioni)
        self.chiamate: list[tuple] = []
        if calendari is None:
            base = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
            generate = [
                partita_dati(i, base + timedelta(days=i), casa=(10 + i, f"Casa {i}"))
                for i in range(1, partite_ft + 1)
            ]
            calendari = {(135, 2026): generate}
        self.calendari = calendari
        self._per_id = {p.id: p for lista in calendari.values() for p in lista}

    def _chiamata(self, *argomenti):
        if self.limite_dopo is not None and len(self.chiamate) >= self.limite_dopo:
            raise LimiteSuperato("limite finto")
        self.chiamate.append(argomenti)

    def partite(self, competizione_id, stagione):
        self._chiamata("partite", competizione_id, stagione)
        return list(self.calendari.get((competizione_id, stagione), []))

    def partita(self, id):
        self._chiamata("partita", id)
        return self._per_id[id]

    def statistiche(self, partita_id):
        self._chiamata("statistiche", partita_id)
        if partita_id in self.errori:
            raise ErroreFonte(f"errore finto sulla partita {partita_id}")
        if partita_id in self.statistiche_vuote:
            return []
        p = self._per_id[partita_id]
        # come /fixtures/players: nessuna griglia (arriva solo da /fixtures/lineups)
        presenze = [
            PresenzaDati(
                partita_id=partita_id,
                giocatore_id=partita_id * 100 + 1,
                giocatore_nome=f"Giocatore {partita_id}",
                squadra_id=p.casa_id,
                titolare=True,
                ruolo="D",
                griglia=None,
                minuti=90,
                gialli=1,
                rossi=0,
                falli_commessi=3,
                falli_subiti=1,
                dribbling_tentati=0,
                dribbling_riusciti=0,
                tiri=1,
                gol=0,
                assist=0,
                voto=6.5,
            )
        ]
        if self.due_squadre:
            presenze.append(
                PresenzaDati(
                    partita_id=partita_id,
                    giocatore_id=partita_id * 100 + 2,
                    giocatore_nome=f"Attaccante {partita_id}",
                    squadra_id=p.trasferta_id,
                    titolare=True,
                    ruolo="F",
                    griglia=None,
                    minuti=90,
                    gialli=0,
                    rossi=0,
                    falli_commessi=1,
                    falli_subiti=3,
                    dribbling_tentati=4,
                    dribbling_riusciti=2,
                    tiri=2,
                    gol=1,
                    assist=0,
                    voto=7.0,
                )
            )
        return presenze

    def formazioni(self, partita_id) -> list[FormazioneDati]:
        self._chiamata("formazioni", partita_id)
        if partita_id in self.errori_formazioni:
            raise ErroreFonte(f"errore finto sulle formazioni della partita {partita_id}")
        return list(self.formazioni_uscite.get(partita_id, []))
