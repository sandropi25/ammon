from sqlalchemy import create_engine, inspect, text

from ammonizioni.db import sessione as modulo_sessione


def test_colonne_quote_aggiunte_a_una_tabella_esistente_in_modo_idempotente(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'vecchio.db'}")
    with engine.begin() as conn:  # database della vecchia versione: partite senza quote
        conn.execute(text("CREATE TABLE partite (id INTEGER PRIMARY KEY, stato VARCHAR)"))
    modulo_sessione.crea_tabelle(engine)
    modulo_sessione.crea_tabelle(engine)  # secondo avvio: nessun errore
    colonne = {c["name"] for c in inspect(engine).get_columns("partite")}
    assert {"prob_casa", "prob_pareggio", "prob_trasferta"} <= colonne
    engine.dispose()


def test_database_nuovo_ha_le_colonne_delle_quote():
    engine = modulo_sessione.crea_engine("sqlite://")
    modulo_sessione.crea_tabelle(engine)
    colonne = {c["name"] for c in inspect(engine).get_columns("partite")}
    assert {"prob_casa", "prob_pareggio", "prob_trasferta"} <= colonne
    engine.dispose()
