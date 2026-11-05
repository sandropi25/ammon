"""Script una tantum scripts/ricarica_minuti.py: DB temporaneo e fonte finta, niente rete."""
import importlib.util
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti.tipi import PresenzaDati

PERCORSO = Path(__file__).resolve().parents[2] / "scripts" / "ricarica_minuti.py"


def carica_script():
    spec = importlib.util.spec_from_file_location("ricarica_minuti", PERCORSO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def aggiungi_partita(s, id, competizione_id=135):
    for sid, nome in ((1, "Juventus"), (2, "Inter")):
        if s.get(Squadra, sid) is None:
            s.add(Squadra(id=sid, nome=nome))
    s.add(
        Partita(
            id=id, data_utc=datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc),
            competizione_id=competizione_id, stagione=2026, casa_id=1, trasferta_id=2,
            stato="FT", statistiche_scaricate=True,
        )
    )
    s.flush()


def aggiungi_presenza(s, partita_id, giocatore_id, *, titolare, minuti, **kw):
    if s.get(Giocatore, giocatore_id) is None:
        s.add(Giocatore(id=giocatore_id, nome=f"G{giocatore_id}"))
        s.flush()
    s.add(
        Presenza(
            partita_id=partita_id, giocatore_id=giocatore_id, squadra_id=1,
            titolare=titolare, minuti=minuti, **kw,
        )
    )
    s.flush()


def dati(partita_id, giocatore_id, minuti, *, titolare=False, gialli=0, falli_commessi=0):
    return PresenzaDati(
        partita_id=partita_id, giocatore_id=giocatore_id, giocatore_nome=f"G{giocatore_id}",
        squadra_id=1, titolare=titolare, ruolo="M", griglia=None, minuti=minuti, gialli=gialli,
        rossi=0, falli_commessi=falli_commessi, falli_subiti=0, dribbling_tentati=0,
        dribbling_riusciti=0, tiri=0, gol=0, assist=0, voto=None,
    )


class FonteDiProva:
    def __init__(self, risposte):
        self.risposte = risposte
        self.chiamate = []

    def statistiche(self, partita_id):
        self.chiamate.append(partita_id)
        return self.risposte[partita_id]


@pytest.fixture
def db_tmp(tmp_path):
    engine = modulo_sessione.crea_engine(f"sqlite:///{tmp_path / 'prova.db'}")
    modulo_sessione.crea_tabelle(engine)

    @contextmanager
    def apri():
        with Session(engine) as s:
            yield s

    with apri() as s:
        # 1: sostituto con 0 minuti ma falli commessi (da ricaricare), in una competizione qualsiasi
        aggiungi_partita(s, 1, competizione_id=137)
        aggiungi_presenza(s, 1, 10, titolare=False, minuti=0, falli_commessi=2)
        aggiungi_presenza(s, 1, 11, titolare=True, minuti=90)
        # 2: panchinaro davvero inutilizzato (nessuna attivita'), anche ammonito: non va ricaricato
        aggiungi_partita(s, 2)
        aggiungi_presenza(s, 2, 12, titolare=False, minuti=0, gialli=1)
        # 3: titolare con 0 minuti e falli: non e' un sostituto
        aggiungi_partita(s, 3)
        aggiungi_presenza(s, 3, 13, titolare=True, minuti=0, falli_commessi=1)
        s.commit()
    yield apri
    engine.dispose()


def test_seleziona_solo_sostituti_con_attivita_e_zero_minuti(db_tmp):
    script = carica_script()
    with db_tmp() as s:
        assert script.partite_da_ricaricare(s) == [1]


def test_senza_esegui_stampa_il_numero_e_non_tocca_nulla(db_tmp, capsys):
    script = carica_script()

    def crea_fonte(s, priorita):
        raise AssertionError("la fonte non deve essere creata in dry run")

    assert script.main([], crea_fonte=crea_fonte, apri=db_tmp) == 0
    assert "1" in capsys.readouterr().out
    with db_tmp() as s:
        assert s.get(Presenza, (1, 10)).minuti == 0


def test_esegui_riscarica_e_sovrascrive_le_presenze(db_tmp, capsys):
    script = carica_script()
    fonte = FonteDiProva({1: [dati(1, 10, 12, falli_commessi=2, gialli=1), dati(1, 11, 90)]})
    assert script.main(["--esegui"], crea_fonte=lambda s, p: fonte, apri=db_tmp) == 0
    assert fonte.chiamate == [1]  # solo la partita selezionata
    with db_tmp() as s:
        p = s.get(Presenza, (1, 10))
        assert (p.minuti, p.gialli, p.titolare) == (12, 1, False)
        assert s.get(Partita, 1).statistiche_scaricate is True
        # le altre partite non sono toccate
        assert s.get(Presenza, (2, 12)).minuti == 0
    assert script.main([], crea_fonte=lambda s, p: fonte, apri=db_tmp) == 0
    assert "0" in capsys.readouterr().out.splitlines()[-1]
