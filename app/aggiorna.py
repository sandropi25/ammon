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

CARTELLA_APP = Path(__file__).resolve().parent
SORGENTI = CARTELLA_APP.parent / "src" / "ammonizioni"
# tutti i moduli dell'app tranne il punto d'ingresso e questo file: ricavati dai file, così
# un modulo nuovo non può essere dimenticato
MODULI_APP = tuple(
    sorted(f.stem for f in CARTELLA_APP.glob("*.py") if f.stem not in ("Partite", "aggiorna"))
)

_firma: tuple[int, int] | None = None


def firma_sorgenti(
    cartella: Path = SORGENTI, cartella_app: Path | None = CARTELLA_APP
) -> tuple[int, int]:
    """(ultima modifica, numero di file) dei sorgenti Python del motore e dei moduli
    dell'app. Anche l'app conta: Streamlit ricarica solo il file cambiato, non i moduli che
    lo usano (es. cache_dati teneva la versione vecchia di componenti_calde e la cache non
    riusciva più a salvare i suoi oggetti: PicklingError)."""
    file = list(cartella.rglob("*.py"))
    if cartella_app is not None:
        file += [f for f in cartella_app.glob("*.py") if f.stem not in ("Partite", "aggiorna")]
    tempi = [f.stat().st_mtime_ns for f in file]
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
    attuale = firma_sorgenti(cartella, CARTELLA_APP if cartella == SORGENTI else None)
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
