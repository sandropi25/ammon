"""scripts/demo_locale.py: il DB dimostrativo si crea e le pagine lo mostrano senza errori."""
import importlib.util

from ayuda_app import (
    PAGINA_DETTAGLIO, PAGINA_GIOCATE, PAGINA_PARTITE, RADICE, avvia, sessione_db, url_db, visibile,
)
from sqlalchemy import func, select

from ammonizioni.db.modelli import Partita


def _modulo():
    spec = importlib.util.spec_from_file_location("demo_locale", RADICE / "scripts" / "demo_locale.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_demo_popola_e_le_pagine_funzionano(url_db, sessione_db):
    _modulo().popola_demo(url_db)
    with sessione_db() as s:
        future = s.execute(select(Partita.id).where(Partita.stato == "NS")).scalars().all()
        assert len(future) == 8
        assert s.execute(select(func.count()).select_from(Partita)).scalar() > 40
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    t = visibile(at)
    assert "Inter" in t and "Milan" in t and "Partita calda" in t and "Derby" in t
    at = avvia(PAGINA_DETTAGLIO, partita=future[0])
    assert not at.exception
    assert any('class="cr-candidato"' in m.value for m in at.markdown)
    at = avvia(PAGINA_GIOCATE, tema="chiaro")
    assert not at.exception
    assert any('class="cr-tessera"' in m.value for m in at.markdown)
