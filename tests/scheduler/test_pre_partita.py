import logging
from datetime import datetime, timedelta, timezone

import pytest
from conftest import FonteFinta
from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti.limite import Priorita
from ammonizioni.fonti.tipi import FormazioneDati
from ammonizioni.scheduler import notte, pre_partita

INIZIO = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)


def prepara(s, partita_id=100, data=INIZIO, stato="NS", competizione=135, probabili=True):
    if s.get(Squadra, 1) is None:
        s.add_all([Squadra(id=1, nome="Casa"), Squadra(id=2, nome="Trasferta")])
        s.add_all([Giocatore(id=i, nome=f"G{i}", ruolo="D") for i in range(1, 9)])
        s.flush()
    s.add(
        Partita(
            id=partita_id, data_utc=data, competizione_id=competizione, stagione=2026,
            casa_id=1, trasferta_id=2, stato=stato,
            stato_formazioni="probabili" if probabili else "ufficiali",
        )
    )
    s.flush()


def ufficiali(partita_id=100):
    return {
        partita_id: [
            FormazioneDati(partita_id, 1, [(1, "G1", "D", "2:1"), (2, "G2", "D", "2:2")]),
            FormazioneDati(partita_id, 2, [(5, "G5", "D", "2:1")]),
        ]
    }


def test_finestra_75_minuti(sessione):
    prepara(sessione)
    ids = lambda adesso: [p.id for p in pre_partita.partite_da_controllare(sessione, adesso)]  # noqa: E731
    assert ids(INIZIO - timedelta(minutes=76)) == []
    assert ids(INIZIO - timedelta(minutes=75)) == [100]
    assert ids(INIZIO - timedelta(minutes=1)) == [100]
    assert ids(INIZIO) == []
    assert ids(INIZIO + timedelta(minutes=1)) == []


def test_solo_serie_a_con_probabili(sessione):
    prepara(sessione, 100, competizione=137)
    prepara(sessione, 101, probabili=False)
    prepara(sessione, 102)
    adesso = INIZIO - timedelta(minutes=30)
    assert [p.id for p in pre_partita.partite_da_controllare(sessione, adesso)] == [102]


def test_partita_rinviata_saltata_senza_richieste(sessione):
    prepara(sessione, 100, stato="PST")
    prepara(sessione, 101, stato="CANC")
    fonte = FonteFinta()
    adesso = INIZIO - timedelta(minutes=30)
    assert pre_partita.esegui(sessione, fonte, adesso) == 0
    assert fonte.chiamate == []


def test_ufficiali_salvate_e_stato_aggiornato(sessione):
    prepara(sessione)
    fonte = FonteFinta(formazioni_uscite=ufficiali())
    adesso = INIZIO - timedelta(minutes=30)
    assert pre_partita.esegui(sessione, fonte, adesso) == 1
    assert fonte.chiamate == [("formazioni", 100)]
    assert sessione.get(Partita, 100).stato_formazioni == "ufficiali"
    righe = sessione.scalars(
        select(Formazione).where(Formazione.tipo == "ufficiale").order_by(Formazione.giocatore_id)
    ).all()
    assert [(f.squadra_id, f.giocatore_id, f.griglia) for f in righe] == [
        (1, 1, "2:1"), (1, 2, "2:2"), (2, 5, "2:1"),
    ]
    # non e' piu' da controllare
    assert pre_partita.partite_da_controllare(sessione, adesso) == []


def test_formazioni_non_uscite_resta_probabili(sessione):
    prepara(sessione)
    fonte = FonteFinta()
    assert pre_partita.esegui(sessione, fonte, INIZIO - timedelta(minutes=30)) == 0
    assert sessione.get(Partita, 100).stato_formazioni == "probabili"
    assert sessione.scalars(select(Formazione).where(Formazione.tipo == "ufficiale")).all() == []


def test_probabili_da_ultimo_xi_se_mancano(sessione):
    prepara(sessione, 50, data=INIZIO - timedelta(days=7), stato="FT")
    sessione.add(
        Presenza(partita_id=50, giocatore_id=3, squadra_id=1, titolare=True, ruolo="D", griglia="2:1")
    )
    sessione.add(
        Presenza(partita_id=50, giocatore_id=6, squadra_id=2, titolare=True, ruolo="D", griglia="2:1")
    )
    prepara(sessione)
    pre_partita.esegui(sessione, FonteFinta(), INIZIO - timedelta(minutes=30))
    probabili = sessione.scalars(
        select(Formazione).where(Formazione.tipo == "probabile", Formazione.partita_id == 100)
    ).all()
    assert sorted((f.squadra_id, f.giocatore_id) for f in probabili) == [(1, 3), (2, 6)]


def test_probabili_esistenti_non_sovrascritte(sessione):
    prepara(sessione)
    sessione.add(Formazione(partita_id=100, squadra_id=1, giocatore_id=4, tipo="probabile"))
    sessione.flush()
    pre_partita.esegui(sessione, FonteFinta(), INIZIO - timedelta(minutes=30))
    probabili = sessione.scalars(select(Formazione).where(Formazione.tipo == "probabile")).all()
    assert [(f.squadra_id, f.giocatore_id) for f in probabili] == [(1, 4)]


def test_errore_fonte_su_una_partita_non_ferma_le_altre(sessione, caplog):
    prepara(sessione, 100)
    prepara(sessione, 101)
    fonte = FonteFinta(formazioni_uscite=ufficiali(101), errori_formazioni={100})
    with caplog.at_level(logging.WARNING, logger="ammonizioni.scheduler.pre_partita"):
        assert pre_partita.esegui(sessione, fonte, INIZIO - timedelta(minutes=30)) == 1
    assert sessione.get(Partita, 100).stato_formazioni == "probabili"
    assert sessione.get(Partita, 101).stato_formazioni == "ufficiali"
    assert any("100" in r.getMessage() for r in caplog.records)


def test_limite_superato_ferma_il_ciclo_senza_errore(sessione):
    prepara(sessione, 100)
    prepara(sessione, 101)
    fonte = FonteFinta(formazioni_uscite=ufficiali(100), limite_dopo=1)
    assert pre_partita.esegui(sessione, fonte, INIZIO - timedelta(minutes=30)) == 1
    assert sessione.get(Partita, 100).stato_formazioni == "ufficiali"
    assert sessione.get(Partita, 101).stato_formazioni == "probabili"


# --- punti di ingresso -----------------------------------------------------


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'prova.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    engine = modulo_sessione.crea_engine(url)
    modulo_sessione.crea_tabelle(engine)
    engine.dispose()
    return url


def dentro_db(url, funzione):
    engine = modulo_sessione.crea_engine(url)
    with Session(engine) as s:
        funzione(s)
        s.commit()
    engine.dispose()


def test_main_senza_chiave_restituisce_2(db_file, caplog):
    chiamate = []
    with caplog.at_level(logging.ERROR):
        codice = pre_partita.main([], crea_fonte=lambda *a: chiamate.append(a))
    assert codice == 2 and chiamate == []
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert notte.main([], crea_fonte=lambda *a: chiamate.append(a)) == 2
    assert chiamate == []


def test_main_pre_partita_senza_partite_nessuna_chiamata(db_file, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "chiave-di-prova")
    dentro_db(db_file, lambda s: prepara(s, data=datetime.now(timezone.utc) + timedelta(hours=5)))
    fonte = FonteFinta()
    assert pre_partita.main([], crea_fonte=lambda s, chiave, priorita: fonte) == 0
    assert fonte.chiamate == []


def test_main_pre_partita_salva_ufficiali(db_file, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "chiave-di-prova")
    dentro_db(db_file, lambda s: prepara(s, data=datetime.now(timezone.utc) + timedelta(minutes=30)))
    fonte = FonteFinta(formazioni_uscite=ufficiali())
    assert pre_partita.main([], crea_fonte=lambda s, chiave, priorita: fonte) == 0
    assert fonte.chiamate == [("formazioni", 100)]

    def controlla(s):
        assert s.get(Partita, 100).stato_formazioni == "ufficiali"

    dentro_db(db_file, controlla)


def test_main_notte_usa_due_fonti_e_restituisce_0(db_file, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "chiave-di-prova")
    richieste = []

    def crea(s, chiave, priorita):
        richieste.append((chiave, priorita))
        return FonteFinta(partite_ft=2)

    assert notte.main([], crea_fonte=crea) == 0
    assert richieste == [("chiave-di-prova", Priorita.OGGI), ("chiave-di-prova", Priorita.STORICO)]


def test_main_notte_con_limite_raggiunto_restituisce_0(db_file, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "chiave-di-prova")
    assert notte.main([], crea_fonte=lambda s, c, p: FonteFinta(partite_ft=3, limite_dopo=1)) == 0
