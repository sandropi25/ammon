import pytest
from sqlalchemy.orm import Session

from ammonizioni.db import sessione as modulo_sessione


@pytest.fixture
def sessione():
    engine = modulo_sessione.crea_engine("sqlite://")
    modulo_sessione.crea_tabelle(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()
