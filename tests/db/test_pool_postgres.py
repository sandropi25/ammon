from ammonizioni.db import sessione


def test_engine_postgres_pool_piccolo_con_ping_e_riciclo():
    engine = sessione.crea_engine("postgresql+psycopg://utente:x@localhost:5432/db")  # non si connette
    try:
        assert engine.pool.size() == 3
        assert engine.pool._max_overflow == 2
        assert engine.pool._recycle == 280
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_engine_per_riusa_lo_stesso_engine(tmp_path):
    url = f"sqlite:///{(tmp_path / 'p.db').as_posix()}"
    assert sessione.engine_per(url) is sessione.engine_per(url)
