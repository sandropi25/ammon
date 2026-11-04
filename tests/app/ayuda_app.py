"""Aiuti per i test dell'app Streamlit (percorsi, AppTest, testo visibile)."""
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
for percorso in (RADICE / "tests" / "motore", RADICE / "app"):
    if str(percorso) not in sys.path:
        sys.path.insert(0, str(percorso))

from streamlit.testing.v1 import AppTest  # noqa: E402

from ammonizioni.db.sessione import apri  # noqa: E402

PAGINA_PARTITE = str(RADICE / "app" / "Partite.py")
PAGINA_DETTAGLIO = str(RADICE / "app" / "pages" / "1_Dettaglio_partita.py")


def visibile(at: AppTest) -> str:
    """Tutto il testo visibile (markdown, avvisi, titoli...) dell'app."""
    pezzi: list[str] = []
    for gruppo in (
        at.markdown, at.caption, at.warning, at.info, at.error, at.success,
        at.title, at.header, at.subheader, at.text, at.expander,
    ):
        for el in gruppo:
            valore = getattr(el, "value", None)
            if valore is None:
                valore = getattr(el, "label", "")
            pezzi.append(str(valore))
    return "\n".join(pezzi)


def avvia(pagina: str, **query) -> AppTest:
    if pagina == PAGINA_DETTAGLIO:
        # si parte dalla pagina principale, cosi' st.page_link trova le altre pagine
        at = AppTest.from_file(PAGINA_PARTITE, default_timeout=30)
        at.switch_page("pages/1_Dettaglio_partita.py")
    else:
        at = AppTest.from_file(pagina, default_timeout=30)
    for chiave, valore in query.items():
        at.query_params[chiave] = str(valore)
    return at.run()


# Le fixture sono qui (e non in un conftest.py) per non oscurare tests/conftest.py,
# che gli altri test importano come modulo conftest.
@pytest.fixture
def url_db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'prova.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


@pytest.fixture
def sessione_db(url_db):
    """Apre una sessione di scrittura sul DB temporaneo (commit a fine blocco)."""
    return lambda: apri(url_db)
