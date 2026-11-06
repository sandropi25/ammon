"""Job notturno con fonti finte: ESPN (FonteFinta) e football-data (FonteFdFinta). Senza rete."""
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import FonteFinta, partita_dati
from sqlalchemy.orm import Session

from ammonizioni.caricamento import notturno
from ammonizioni.db import repo
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Arbitro, Giocata, Giocatore, Partita, UltimoAggiornamento
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.football_data import ArbitroPartita
from ammonizioni.fonti.limite import LimiteSuperato
from ammonizioni.giocate.registro import aggiungi_giocata
from ammonizioni.scheduler import notte

ADESSO = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
AGGIORNA_BIO_VERA = notte.aggiorna_biografie  # prima che la fixture la sostituisca


@pytest.fixture(autouse=True)
def _biografie_senza_rete(monkeypatch):
    """Il passo delle biografie andrebbe in rete (ESPN, Wikipedia): nei test non fa nulla."""
    from ammonizioni.caricamento.biografie import RiepilogoBio

    chiamate = []

    def finto(s):
        chiamate.append(s)
        return RiepilogoBio()

    monkeypatch.setattr(notte, "aggiorna_biografie", finto)
    return chiamate
INIZIO = ADESSO - timedelta(days=1)  # Juventus-Inter di ieri sera


class FonteFdFinta:
    def __init__(self, voci=(), chiave="chiave-finta", errore=None):
        self.chiave = chiave
        self.voci = list(voci)
        self.errore = errore
        self.chiamate = []

    def arbitri(self, codice, dal, al):
        self.chiamate.append((codice, dal, al))
        if self.errore is not None:
            raise self.errore
        return list(self.voci)


def voce_ieri(arbitro="Daniele Doveri"):
    return ArbitroPartita(INIZIO, "Juventus FC", "FC Internazionale Milano", 1, arbitro)


def partita_senza_arbitro(id=7):
    return partita_dati(id, INIZIO, arbitro=None)


def test_notte_stat_arbitri_esiti(sessione):
    """Calendario, statistiche, arbitro collegato da football-data, esito della giocata."""
    notturno.aggiorna_calendario(sessione, FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]}))
    sessione.add(Giocatore(id=701, nome="Giocatore 7"))
    giocata = aggiungi_giocata(sessione, 7, 701, "Tipster", 3.0, 10.0, date(2026, 9, 6))
    sessione.commit()
    fonte = FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]})
    fd = FonteFdFinta([voce_ieri()])

    r = notturno.esegui(sessione, fonte, adesso=ADESSO, fonte_fd=fd)

    assert r.completo is True
    assert r.partite_aggiornate == 1
    partita = sessione.get(Partita, 7)
    assert partita.statistiche_scaricate is True
    assert sessione.get(Arbitro, partita.arbitro_id).nome_normalizzato == "doveri"
    assert sessione.get(Giocata, giocata.id).esito == "vinta"
    assert fd.chiamate == [("SA", date(2026, 8, 31), date(2026, 9, 14))]  # da -7 a +7 giorni
    assert sessione.get(UltimoAggiornamento, "notte").completo is True


def test_notte_senza_fonte_fd_non_collega(sessione):
    r = notturno.esegui(
        sessione, FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]}), adesso=ADESSO
    )
    assert r.completo is True
    assert sessione.get(Partita, 7).arbitro_id is None


def test_notte_senza_chiave_football_data_salta_gli_arbitri_e_logga(sessione, caplog):
    fd = FonteFdFinta([voce_ieri()], chiave=None)
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.arbitri_fd"):
        r = notturno.esegui(
            sessione, FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]}),
            adesso=ADESSO, fonte_fd=fd,
        )
    assert fd.chiamate == []
    assert r.completo is True and r.partite_aggiornate == 1  # il resto funziona
    assert sessione.get(Partita, 7).arbitro_id is None
    assert any("FOOTBALL_DATA_KEY" in x.getMessage() for x in caplog.records)


@pytest.mark.parametrize("errore", [ErroreFonte("HTTP 403"), LimiteSuperato("limite")])
def test_notte_errore_football_data_non_ferma_il_resto(sessione, caplog, errore):
    fd = FonteFdFinta([voce_ieri()], errore=errore)
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.notturno"):
        r = notturno.esegui(
            sessione, FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]}),
            adesso=ADESSO, fonte_fd=fd,
        )
    assert r.completo is False
    assert r.partite_aggiornate == 1
    assert sessione.get(Partita, 7).statistiche_scaricate is True
    assert sessione.get(Partita, 7).arbitro_id is None
    assert sessione.get(UltimoAggiornamento, "notte").completo is False
    assert any("Arbitri Serie A non collegati" in x.getMessage() for x in caplog.records)


def test_notte_con_ostacoli_alla_fonte_principale_collega_comunque_gli_arbitri(sessione):
    """Limite ESPN raggiunto a meta': completo=False ma gli arbitri delle partite note si collegano."""
    notturno.salva_partita(sessione, partita_senza_arbitro())
    sessione.commit()
    fonte = FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]}, limite_dopo=0)
    fd = FonteFdFinta([voce_ieri()])
    r = notturno.esegui(sessione, fonte, adesso=ADESSO, fonte_fd=fd)
    assert r.completo is False
    assert sessione.get(Partita, 7).arbitro_id is not None


def test_controllo_con_problemi_logga_segna_incompleto_e_prosegue(sessione, caplog):
    chiesti = []

    def controllo(fonte):
        chiesti.append(fonte)
        return ["statistica 'foulsCommitted' mancante (22 giocatori)"]

    fonte = FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]})
    with caplog.at_level(logging.ERROR, logger="ammonizioni.caricamento.notturno"):
        r = notturno.esegui(sessione, fonte, adesso=ADESSO, controllo=controllo)
    assert chiesti == [fonte]
    assert r.completo is False
    assert r.partite_aggiornate == 1  # il resto del lavoro e' stato fatto
    assert sessione.get(UltimoAggiornamento, "notte").completo is False
    messaggi = [x.getMessage() for x in caplog.records if x.levelno == logging.ERROR]
    assert messaggi == [
        "La struttura dei dati ESPN è cambiata: statistica 'foulsCommitted' mancante (22 giocatori)"
    ]


def test_controllo_che_solleva_non_ferma_il_job(sessione, caplog):
    """Anche un controllo che esplode: problema nel log, completo=False, statistiche ed esiti fatti."""
    notturno.aggiorna_calendario(sessione, FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]}))
    sessione.add(Giocatore(id=701, nome="Giocatore 7"))
    giocata = aggiungi_giocata(sessione, 7, 701, "Tipster", 3.0, 10.0, date(2026, 9, 6))
    sessione.commit()

    def controllo(fonte):
        raise AttributeError("'str' object has no attribute 'get'")

    fd = FonteFdFinta([voce_ieri()])
    fonte = FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]})
    with caplog.at_level(logging.ERROR, logger="ammonizioni.caricamento.notturno"):
        r = notturno.esegui(sessione, fonte, adesso=ADESSO, fonte_fd=fd, controllo=controllo)
    assert r.completo is False
    assert sessione.get(Partita, 7).statistiche_scaricate is True
    assert sessione.get(Partita, 7).arbitro_id is not None
    assert sessione.get(Giocata, giocata.id).esito == "vinta"
    assert sessione.get(UltimoAggiornamento, "notte").completo is False
    assert any("struttura dei dati ESPN è cambiata: struttura inattesa" in x.getMessage()
               for x in caplog.records)


def test_controllo_senza_problemi_lascia_completo(sessione):
    fonte = FonteFinta(calendari={(135, 2026): [partita_senza_arbitro()]})
    r = notturno.esegui(sessione, fonte, adesso=ADESSO, controllo=lambda f: [])
    assert r.completo is True


# --- main completo: notte + storico --------------------------------------------


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'notte.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    for nome in ("API_FOOTBALL_KEY", "FOOTBALL_DATA_KEY", "FONTE_DATI", "STORICO_MAX_MINUTI"):
        monkeypatch.delenv(nome, raising=False)
    engine = modulo_sessione.crea_engine(url)
    modulo_sessione.crea_tabelle(engine)
    engine.dispose()
    return url


@contextmanager
def leggi_db(url):
    engine = modulo_sessione.crea_engine(url)
    try:
        with Session(engine) as s:
            yield s
    finally:
        engine.dispose()


def test_main_notte_con_espn_e_football_data_finti(db_file):
    """Notte (calendario, stats, arbitri, esiti) e storico (arbitri della stagione passata)."""
    adesso = datetime.now(timezone.utc)
    ieri = adesso - timedelta(days=1)
    scorsa = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)  # stagione 2025
    calendari = {
        (135, 2026): [partita_dati(7, ieri, arbitro=None)],
        (135, 2025): [partita_dati(8, scorsa, stagione=2025, arbitro=None)],
    }
    fd = FonteFdFinta([
        ArbitroPartita(ieri, "Juventus FC", "FC Internazionale Milano", 1, "Daniele Doveri"),
        ArbitroPartita(scorsa, "Juventus FC", "FC Internazionale Milano", 2, "Davide Massa"),
    ])
    fonti = []

    def crea(s, priorita):
        fonti.append(FonteFinta(calendari=calendari))
        return fonti[-1]

    assert notte.main([], crea_fonte=crea, crea_fd=lambda s: fd, controllo=lambda f: []) == 0

    with leggi_db(db_file) as s:
        assert s.get(Partita, 7).statistiche_scaricate is True
        assert s.get(Arbitro, s.get(Partita, 7).arbitro_id).nome_normalizzato == "doveri"
        assert s.get(Partita, 8).statistiche_scaricate is True  # storico
        assert s.get(Arbitro, s.get(Partita, 8).arbitro_id).nome_normalizzato == "massa"
        assert s.get(UltimoAggiornamento, "notte").completo is True
        assert s.get(UltimoAggiornamento, "storico").completo is True
        assert sorted(repo.leggi_impostazione(s, "arbitri_collegati")) == [2025, 2026]
    # la finestra della notte, poi una sola richiesta per la stagione intera (1 luglio - 30
    # giugno); per il 2026 la notte ha gia' collegato tutto: nessuna richiesta
    assert len(fd.chiamate) == 2
    assert fd.chiamate[1] == ("SA", date(2025, 7, 1), date(2026, 6, 30))
    assert len(fonti) == 2


def test_main_notte_controllo_di_salute_solo_con_espn(db_file, monkeypatch):
    chiamate = []

    def controllo(fonte):
        chiamate.append(fonte)
        return []

    notte.main([], crea_fonte=lambda s, p: FonteFinta(), crea_fd=lambda s: None, controllo=controllo)
    assert len(chiamate) == 1  # FONTE_DATI assente: ESPN
    chiamate.clear()
    monkeypatch.setenv("FONTE_DATI", "api_football")
    notte.main([], crea_fonte=lambda s, p: FonteFinta(), crea_fd=lambda s: None, controllo=controllo)
    assert chiamate == []


def test_main_notte_api_football_non_usa_football_data(db_file, monkeypatch):
    monkeypatch.setenv("FONTE_DATI", "api_football")
    creati = []

    def crea_fd(s):
        creati.append(s)
        return FonteFdFinta([voce_ieri()])

    ieri = datetime.now(timezone.utc) - timedelta(days=1)
    calendari = {(135, 2026): [partita_dati(7, ieri, arbitro=None)]}
    assert notte.main(
        [], crea_fonte=lambda s, p: FonteFinta(calendari=calendari), crea_fd=crea_fd
    ) == 0
    assert creati == []
    with leggi_db(db_file) as s:
        assert s.get(Partita, 7).arbitro_id is None  # nessun collegamento da football-data


def test_main_notte_struttura_cambiata_completo_false_e_prosegue(db_file, caplog):
    ieri = datetime.now(timezone.utc) - timedelta(days=1)
    calendari = {(135, 2026): [partita_dati(7, ieri)]}
    with caplog.at_level(logging.ERROR):
        codice = notte.main(
            [],
            crea_fonte=lambda s, p: FonteFinta(calendari=calendari),
            crea_fd=lambda s: None,
            controllo=lambda f: ["manca 'rosters'"],
        )
    assert codice == 0
    assert any("La struttura dei dati ESPN è cambiata: manca 'rosters'" in x.getMessage()
               for x in caplog.records)
    with leggi_db(db_file) as s:
        assert s.get(UltimoAggiornamento, "notte").completo is False
        assert s.get(Partita, 7).statistiche_scaricate is True


def test_main_notte_aggiorna_le_biografie(db_file, _biografie_senza_rete):
    notte.main([], crea_fonte=lambda s, p: FonteFinta(), crea_fd=lambda s: None, controllo=lambda f: [])
    assert len(_biografie_senza_rete) == 1


def test_main_notte_errore_biografie_non_ferma_lo_storico(db_file, caplog):
    def guasto(s):
        raise RuntimeError("wikipedia giu'")

    with caplog.at_level(logging.ERROR):
        assert notte.main(
            [], crea_fonte=lambda s, p: FonteFinta(), crea_fd=lambda s: None,
            controllo=lambda f: [], biografie=guasto,
        ) == 0
    assert any("Biografie non aggiornate" in x.getMessage() for x in caplog.records)
    with leggi_db(db_file) as s:
        assert s.get(UltimoAggiornamento, "storico") is not None


def test_biografie_della_notte_usano_espn_solo_con_fonte_espn(sessione, monkeypatch):
    usati = []
    monkeypatch.setattr(
        notte.biografie_giocatori, "aggiorna",
        lambda s, client, usa_espn: usati.append((client.limite is not None, usa_espn)),
    )
    monkeypatch.delenv("FONTE_DATI", raising=False)
    AGGIORNA_BIO_VERA(sessione)
    monkeypatch.setenv("FONTE_DATI", "api_football")
    AGGIORNA_BIO_VERA(sessione)
    assert usati == [(True, True), (False, False)]


