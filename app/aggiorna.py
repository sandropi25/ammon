"""Ricarica il motore (`src/ammonizioni`) quando i suoi sorgenti cambiano.

Streamlit, dopo un aggiornamento del codice, ricarica da solo solo i moduli della
cartella dell'app: il pacchetto del motore restava in memoria nella versione vecchia
(ImportError su funzioni nuove). Ogni pagina chiama `ricarica_se_cambiato()` prima di
importare i propri moduli: se i sorgenti del motore sono cambiati, toglie dalla memoria
il motore e i moduli dell'app che lo usano, così vengono reimportati nuovi.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

SORGENTI = Path(__file__).resolve().parents[1] / "src" / "ammonizioni"
MODULI_APP = ("componenti", "componenti_giocate", "componenti_cerca", "cache_dati", "stile", "auth")

_firma: tuple[int, int] | None = None


def firma_sorgenti(cartella: Path = SORGENTI) -> tuple[int, int]:
    """(ultima modifica, numero di file) dei sorgenti Python del motore."""
    tempi = [p.stat().st_mtime_ns for p in cartella.rglob("*.py")]
    return (max(tempi, default=0), len(tempi))


def _togli_moduli(pacchetto: str, moduli_app: tuple[str, ...]) -> None:
    for nome in list(sys.modules):
        if nome == pacchetto or nome.startswith(pacchetto + ".") or nome in moduli_app:
            del sys.modules[nome]


def ricarica_se_cambiato(
    svuota_cache: Callable[[], None] | None = None,
    cartella: Path = SORGENTI,
    pacchetto: str = "ammonizioni",
    moduli_app: tuple[str, ...] = MODULI_APP,
) -> bool:
    """True se ha tolto i moduli dalla memoria (verranno reimportati aggiornati).

    Alla prima chiamata del processo (o dopo che questo file è stato ricaricato) toglie
    comunque il motore eventualmente già in memoria: non si sa con quale versione era
    stato importato."""
    global _firma
    attuale = firma_sorgenti(cartella)
    if _firma == attuale:
        return False
    _firma = attuale
    if pacchetto == "ammonizioni" and "PYTEST_CURRENT_TEST" in os.environ:
        # nei test le pagine girano nello stesso processo dei test: togliere il motore
        # vero creerebbe due copie delle sue classi. Il comportamento è provato con
        # moduli finti in tests/app/test_aggiorna.py.
        return False
    _togli_moduli(pacchetto, moduli_app)
    if svuota_cache is not None:
        svuota_cache()
    return True
