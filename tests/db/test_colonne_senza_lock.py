from sqlalchemy import create_engine, event

from ammonizioni.db import sessione


def test_colonne_mancanti_solo_quelle_assenti():
    tutte = {}
    for t, c, _ in sessione.COLONNE_AGGIUNTE:
        tutte.setdefault(t, set()).add(c)
    assert sessione.colonne_mancanti(tutte) == []
    t0, c0, tipo0 = sessione.COLONNE_AGGIUNTE[0]
    meno_una = {t: set(c) for t, c in tutte.items()}
    meno_una[t0].discard(c0)
    assert sessione.colonne_mancanti(meno_una) == [(t0, c0, tipo0)]


def test_seconda_apertura_non_altera_nessuna_tabella(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    sessione.crea_tabelle(engine)  # prima volta: schema completo
    istruzioni = []
    event.listen(engine, "before_cursor_execute", lambda *a: istruzioni.append(a[2]))
    sessione.crea_tabelle(engine)  # come un secondo processo che apre lo stesso DB
    assert not [q for q in istruzioni if q.strip().upper().startswith("ALTER")]
    engine.dispose()
