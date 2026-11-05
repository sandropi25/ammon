"""scripts/demo_locale.py: il DB dimostrativo si crea e le pagine lo mostrano senza errori."""
import importlib.util

from ayuda_app import (
    PAGINA_CALDE, PAGINA_CALENDARIO, PAGINA_DETTAGLIO, PAGINA_GIOCATE, PAGINA_IMPOSTAZIONI,
    PAGINA_PARTITE, RADICE, avvia, sessione_db, url_db, visibile,
)
from sqlalchemy import func, select

from ammonizioni.db.modelli import ListaManuale, Partita


def _modulo():
    spec = importlib.util.spec_from_file_location("demo_locale", RADICE / "scripts" / "demo_locale.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_demo_popola_e_le_pagine_funzionano(url_db, sessione_db):
    _modulo().popola_demo(url_db)
    with sessione_db() as s:
        future = s.execute(select(Partita.id).where(Partita.stato == "NS")).scalars().all()
        assert len(future) == 9
        assert s.execute(select(func.count()).select_from(Partita)).scalar() > 40
    at = avvia(PAGINA_PARTITE)
    assert not at.exception
    t = visibile(at)
    assert "Inter" in t and "Milan" in t and "Partita calda" in t and "Derby" in t
    # derby, campo caldo e partita calda sono automatici: nessuna riga nelle liste manuali
    with sessione_db() as s:
        assert s.execute(select(func.count()).select_from(ListaManuale)).scalar() == 0
    at = avvia(PAGINA_CALDE)
    assert not at.exception
    t = visibile(at)
    assert "Derby: Inter – Milan" in t and "Derby: Roma – Lazio" in t
    assert "campo caldo: Napoli in casa" in t  # il Napoli in casa, non un derby
    assert "Il resto della stagione" in t  # il derby lontano
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    t = visibile(at)
    assert "Inter – Milan" in t and "Napoli in casa:" in t
    at = avvia(PAGINA_DETTAGLIO, partita=future[0])
    assert not at.exception
    assert any('class="cr-candidato"' in m.value for m in at.markdown)
    # Calendario: si apre sulla giornata 9 (da giocare); la 8 ha risultati e cartellini
    at = avvia(PAGINA_CALENDARIO)
    assert not at.exception and "Giornata 9" in visibile(at)
    at.button(key="calendario_precedente").click().run()
    assert not at.exception and "Giornata 8" in visibile(at)
    schede = [m.value for m in at.markdown if 'class="cr-partita"' in m.value]
    assert len(schede) == 4 and all("cr-gol" in x and "🟨" in x for x in schede)
    assert any("🟥 1 rosso" in x for x in schede)  # il rosso del subentrato dalla panchina
    at = avvia(PAGINA_GIOCATE, tema="chiaro")
    assert not at.exception
    assert any('class="cr-tessera"' in m.value for m in at.markdown)
