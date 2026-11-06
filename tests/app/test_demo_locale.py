"""scripts/demo_locale.py: il DB dimostrativo si crea e le pagine lo mostrano senza errori."""
import importlib.util

from ayuda_app import (
    PAGINA_CALDE, PAGINA_CALENDARIO, PAGINA_DETTAGLIO, PAGINA_GIOCATE, PAGINA_HOME, PAGINA_IMPOSTAZIONI,
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
    # probabili subentranti: tabella a parte (la prima partita ha le ufficiali e la panchina)
    assert "Probabili subentranti" in [h.value for h in at.subheader]
    assert any("cr-subentrante" in m.value and "subentrante · può entrare" in m.value
               for m in at.markdown)
    # campo: stemmi ESPN, colori sociali, numeri di maglia e panchina ufficiale
    campo = next(m.value for m in at.markdown if 'class="cr-campo"' in m.value)
    assert "https://a.espncdn.com/i/teamlogos/soccer/500/110.png" in campo  # Inter
    assert 'fill="#0068A8"' in campo and ">10<" not in campo and ">14<" in campo
    assert "Panchina · Inter" in campo and ">19 " in campo
    # anche con le formazioni probabili (panchina calcolata dalle ultime partite)
    at = avvia(PAGINA_DETTAGLIO, partita=future[1])
    assert not at.exception
    assert "Probabili subentranti" in [h.value for h in at.subheader]
    # Calendario: si apre sulla giornata 9 (da giocare); la 8 ha risultati e cartellini
    at = avvia(PAGINA_CALENDARIO)
    assert not at.exception and "Giornata 9" in visibile(at)
    at.button(key="calendario_precedente").click().run()
    assert not at.exception and "Giornata 8" in visibile(at)
    schede = [m.value for m in at.markdown if 'class="cr-partita"' in m.value]
    assert len(schede) == 4 and all("cr-gol" in x and "🟨" in x for x in schede)
    assert any("🟥 1 rosso" in x for x in schede)  # il rosso del subentrato dalla panchina
    # Home: riquadri, classifica, grafici e biografie dimostrative
    at = avvia(PAGINA_HOME)
    assert not at.exception
    t = visibile(at)
    assert "Partita più calda" in t and "Inter – Milan" in t
    assert "Profili dei più ammoniti" in t and "calciatore inventato" in t
    # menu della Serie A aperto: la giornata 9 con il derby caldo
    at.session_state["menu_serie-a"] = True
    at.run()
    voci = [m.value for m in at.markdown if 'class="cr-voce-menu"' in m.value]
    assert any("Inter" in v and "Milan" in v and "🔥" in v for v in voci)
    at = avvia(PAGINA_GIOCATE, tema="chiaro")
    assert not at.exception
    assert any('class="cr-tessera"' in m.value for m in at.markdown)
