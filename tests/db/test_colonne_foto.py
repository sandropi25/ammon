from sqlalchemy import create_engine, event, text

from ammonizioni.db import sessione


def test_colonne_foto_nella_migrazione():
    aggiunte = {(t, c) for t, c, _ in sessione.COLONNE_AGGIUNTE}
    assert ("giocatori", "foto_url") in aggiunte
    assert ("giocatori", "foto_controllata") in aggiunte


def test_database_vecchio_riceve_le_colonne_foto_una_volta_sola(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'vecchio.sqlite'}")
    with engine.begin() as conn:  # tabella giocatori della prima versione
        conn.execute(text("CREATE TABLE giocatori (id INTEGER PRIMARY KEY, nome VARCHAR)"))
        conn.execute(text("INSERT INTO giocatori (id, nome) VALUES (1, 'Yerry Mina')"))
    sessione.crea_tabelle(engine)
    with engine.connect() as conn:
        colonne = {r[1] for r in conn.execute(text("PRAGMA table_info(giocatori)"))}
        assert {"foto_url", "foto_controllata"} <= colonne
        assert conn.execute(text("SELECT foto_url FROM giocatori")).scalar() is None
    istruzioni = []
    event.listen(engine, "before_cursor_execute", lambda *a: istruzioni.append(a[2]))
    sessione.crea_tabelle(engine)
    assert not [q for q in istruzioni if q.strip().upper().startswith("ALTER")]
    engine.dispose()
