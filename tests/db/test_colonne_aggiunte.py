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


COLONNE_BIO = {
    "data_nascita", "nazionalita", "altezza_cm", "posizione", "wiki_titolo", "wiki_url",
    "wiki_estratto", "bio_aggiornata",
}


def test_colonne_biografia_aggiunte_a_giocatori_esistenti_in_modo_idempotente(tmp_path):
    from datetime import date, datetime, timezone

    from sqlalchemy.orm import Session

    from ammonizioni.db.modelli import Giocatore

    engine = create_engine(f"sqlite:///{tmp_path / 'vecchio.db'}")
    with engine.begin() as conn:  # vecchia versione: giocatori senza biografia
        conn.execute(text(
            "CREATE TABLE giocatori (id INTEGER PRIMARY KEY, nome VARCHAR, ruolo VARCHAR(1), "
            "sofascore_url VARCHAR)"
        ))
        conn.execute(text("INSERT INTO giocatori (id, nome) VALUES (1, 'Mario Rossi')"))
    modulo_sessione.crea_tabelle(engine)
    modulo_sessione.crea_tabelle(engine)
    colonne = {c["name"] for c in inspect(engine).get_columns("giocatori")}
    assert COLONNE_BIO <= colonne
    with Session(engine) as s:  # le colonne nuove si leggono e si scrivono
        g = s.get(Giocatore, 1)
        assert g.nome == "Mario Rossi" and g.bio_aggiornata is None
        g.data_nascita = date(1994, 3, 17)
        g.bio_aggiornata = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
        g.wiki_estratto = "Testo lungo " * 100
        s.commit()
        s.expire_all()
        g = s.get(Giocatore, 1)
        assert g.data_nascita == date(1994, 3, 17)
        assert g.bio_aggiornata == datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
    engine.dispose()


def test_colonne_cartellini_totali_aggiunte_in_modo_idempotente(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'vecchio.db'}")
    with engine.begin() as conn:  # database della vecchia versione
        conn.execute(text("CREATE TABLE partite (id INTEGER PRIMARY KEY, stato VARCHAR)"))
        conn.execute(text("INSERT INTO partite (id, stato) VALUES (1, 'FT')"))
    modulo_sessione.crea_tabelle(engine)
    modulo_sessione.crea_tabelle(engine)
    colonne = {c["name"] for c in inspect(engine).get_columns("partite")}
    assert {"gialli_totali", "rossi_totali", "falli_totali"} <= colonne
    with engine.connect() as conn:  # le partite vecchie restano "non note", non zero
        riga = conn.execute(
            text("SELECT gialli_totali, rossi_totali, falli_totali FROM partite")
        ).one()
    assert tuple(riga) == (None, None, None)
    engine.dispose()


def test_database_nuovo_ha_le_colonne_delle_quote():
    engine = modulo_sessione.crea_engine("sqlite://")
    modulo_sessione.crea_tabelle(engine)
    colonne = {c["name"] for c in inspect(engine).get_columns("partite")}
    assert {"prob_casa", "prob_pareggio", "prob_trasferta"} <= colonne
    engine.dispose()
