import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ammonizioni.db import repo
from ammonizioni.db.modelli import Arbitro, Partita, Squadra
from ammonizioni.db.sessione import apri

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "copia_database.py"


def _modulo():
    spec = importlib.util.spec_from_file_location("copia_database", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _popola(url):
    with apri(url) as s:
        s.add_all([Squadra(id=1, nome="Casa"), Squadra(id=2, nome="Ospite")])
        s.add(Arbitro(nome_normalizzato="rossi", nome_visualizzato="Rossi"))
        s.flush()
        s.add(Partita(id=10, data_utc=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
                      competizione_id=135, stagione=2025, casa_id=1, trasferta_id=2,
                      stato="FT", stato_formazioni="ufficiali", statistiche_scaricate=True))
        repo.scrivi_impostazione(s, "fonte_dati_db", "espn")


def test_copia_tutte_le_tabelle_e_le_date_restano_utc(tmp_path):
    origine = f"sqlite:///{tmp_path / 'origine.db'}"
    destinazione = f"sqlite:///{tmp_path / 'dest.db'}"
    _popola(origine)
    copiate = _modulo().copia(origine, destinazione)
    assert copiate["partite"] == 1 and copiate["squadre"] == 2
    with apri(destinazione) as s:
        p = s.get(Partita, 10)
        assert p.data_utc == datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
        assert s.scalar(select(func.count()).select_from(Arbitro)) == 1
        assert repo.leggi_impostazione(s, "fonte_dati_db", None) == "espn"
        # i nuovi id automatici partono dopo quelli copiati
        s.add(Arbitro(nome_normalizzato="bianchi", nome_visualizzato="Bianchi"))
        s.flush()


def test_rifiuta_destinazione_non_vuota(tmp_path):
    origine = f"sqlite:///{tmp_path / 'origine.db'}"
    destinazione = f"sqlite:///{tmp_path / 'dest.db'}"
    _popola(origine)
    _popola(destinazione)
    with pytest.raises(SystemExit, match="non e' vuoto"):
        _modulo().copia(origine, destinazione)
