from datetime import datetime, timezone

from sqlalchemy import select

from ammonizioni.db import repo
from ammonizioni.db.modelli import Presenza


def _presenza(**extra):
    base = dict(
        partita_id=1, giocatore_id=10, squadra_id=5, titolare=True, ruolo="M",
        griglia="4:2", minuti=90, gialli=0, rossi=0, falli_commessi=1,
        falli_subiti=2, dribbling_tentati=0, dribbling_riusciti=0, tiri=1,
        gol=0, assist=0, voto=6.5,
    )
    base.update(extra)
    return Presenza(**base)


def test_upsert_presenza_idempotente(sessione):
    repo.upsert(sessione, _presenza())
    sessione.flush()
    repo.upsert(sessione, _presenza(gialli=1, minuti=80))
    sessione.flush()
    righe = sessione.scalars(select(Presenza)).all()
    assert len(righe) == 1
    assert righe[0].gialli == 1
    assert righe[0].minuti == 80


def test_impostazione_roundtrip(sessione):
    repo.scrivi_impostazione(sessione, "pesi", {"a": 1})
    assert repo.leggi_impostazione(sessione, "pesi", None) == {"a": 1}


def test_impostazione_default(sessione):
    assert repo.leggi_impostazione(sessione, "manca", 42) == 42


def test_ultimo_aggiornamento_none_se_mai_eseguito(sessione):
    assert repo.ultimo_aggiornamento(sessione, "scarico") is None


def test_segna_aggiornamento(sessione):
    repo.segna_aggiornamento(sessione, "scarico", True)
    quando = repo.ultimo_aggiornamento(sessione, "scarico")
    assert quando is not None
    assert (datetime.now(timezone.utc).replace(tzinfo=None) - quando.replace(tzinfo=None)).total_seconds() < 60
