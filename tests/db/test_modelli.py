from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from ammonizioni.db import repo
from ammonizioni.db import sessione as sessione_mod
from ammonizioni.db.modelli import Partita, Presenza, Squadra


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
    assert quando.tzinfo is not None
    assert (datetime.now(timezone.utc) - quando).total_seconds() < 60


def _partita(id, data):
    return Partita(id=id, data_utc=data, competizione_id=135, stagione=2026,
                   casa_id=1, trasferta_id=2)


def test_filtro_con_datetime_aware_non_utc(sessione):
    sessione.add_all([Squadra(id=1, nome="A"), Squadra(id=2, nome="B")])
    sessione.add_all([
        _partita(1, datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)),
        _partita(2, datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)),
    ])
    sessione.flush()
    # 13:00 a UTC+2 = 11:00 UTC: separa le due partite
    limite = datetime(2026, 11, 1, 13, 0, tzinfo=timezone(timedelta(hours=2)))
    ids = sessione.scalars(
        select(Partita.id).where(Partita.data_utc > limite)
    ).all()
    assert ids == [2]
    letta = sessione.get(Partita, 1)
    assert letta.data_utc == datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    assert letta.data_utc.tzinfo is not None


def test_datetime_naive_rifiutato(sessione):
    sessione.add_all([Squadra(id=1, nome="A"), Squadra(id=2, nome="B")])
    sessione.add(_partita(1, datetime(2026, 11, 1, 10, 0)))
    with pytest.raises(StatementError) as e:
        sessione.flush()
    assert isinstance(e.value.orig, ValueError)


def test_apri_commit_su_successo(tmp_path):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    with sessione_mod.apri(url) as s:
        repo.scrivi_impostazione(s, "k", 1)
    with sessione_mod.apri(url) as s:
        assert repo.leggi_impostazione(s, "k", None) == 1


def test_apri_rollback_su_eccezione(tmp_path):
    url = f"sqlite:///{tmp_path / 'b.db'}"
    with pytest.raises(RuntimeError):
        with sessione_mod.apri(url) as s:
            repo.scrivi_impostazione(s, "k", 1)
            raise RuntimeError("errore")
    with sessione_mod.apri(url) as s:
        assert repo.leggi_impostazione(s, "k", None) is None


def test_apri_url_da_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    with sessione_mod.apri() as s:
        repo.scrivi_impostazione(s, "k", "env")
    assert (tmp_path / "c.db").exists()
    with sessione_mod.apri() as s:
        assert repo.leggi_impostazione(s, "k", None) == "env"
