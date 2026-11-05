import logging
from datetime import datetime, timedelta, timezone

import pytest
from conftest import FonteFinta
from sqlalchemy import select
from sqlalchemy.orm import Session

from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import (
    Formazione,
    Giocatore,
    Partita,
    Presenza,
    Squadra,
    UltimoAggiornamento,
)
from ammonizioni.fonti.api_football import ApiFootball
from ammonizioni.fonti.espn import Espn
from ammonizioni.fonti.football_data import FootballData
from ammonizioni.fonti.limite import LimiteRichieste, Priorita
from ammonizioni.fonti.tipi import FormazioneDati
from ammonizioni.scheduler import comune, notte, pre_partita

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


def test_anche_la_liga_e_controllata_la_copa_del_rey_no(sessione):
    prepara(sessione, 100, competizione=140)
    prepara(sessione, 101, competizione=143)
    prepara(sessione, 102)  # Serie A
    adesso = INIZIO - timedelta(minutes=30)
    assert [p.id for p in pre_partita.partite_da_controllare(sessione, adesso)] == [102, 100]


def test_serie_a_servita_prima_della_liga_anche_se_piu_tarda(sessione):
    prepara(sessione, 100, data=INIZIO - timedelta(minutes=20), competizione=140)  # prima
    prepara(sessione, 101, data=INIZIO)  # Serie A, dopo
    prepara(sessione, 102, data=INIZIO - timedelta(minutes=10), competizione=140)
    adesso = INIZIO - timedelta(minutes=60)
    assert [p.id for p in pre_partita.partite_da_controllare(sessione, adesso)] == [101, 100, 102]
    # le richieste seguono lo stesso ordine: se il limite finisce, la Serie A e' gia' servita
    fonte = FonteFinta()
    pre_partita.esegui(sessione, fonte, adesso)
    assert fonte.chiamate == [("formazioni", 101), ("formazioni", 100), ("formazioni", 102)]


def test_la_fonte_sa_la_competizione_della_partita(sessione):
    """In un processo nuovo ESPN non conosce lo slug: gli arriva dal database."""
    class FonteConCompetizione(FonteFinta):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.indicate = []

        def indica_competizione(self, partita_id, competizione_id):
            self.indicate.append((partita_id, competizione_id))

    prepara(sessione, 100, competizione=140)
    fonte = FonteConCompetizione(formazioni_uscite=ufficiali())
    assert pre_partita.esegui(sessione, fonte, INIZIO - timedelta(minutes=30)) == 1
    assert fonte.indicate == [(100, 140)]
    assert fonte.chiamate == [("formazioni", 100)]


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


@pytest.mark.parametrize(
    "arrivate",
    [
        [FormazioneDati(100, 1, [(1, "G1", "D", "2:1"), (2, "G2", "D", "2:2")])],
        [
            FormazioneDati(100, 1, [(1, "G1", "D", "2:1"), (2, "G2", "D", "2:2")]),
            FormazioneDati(100, 2, []),
        ],
    ],
    ids=["una_squadra_sola", "trasferta_senza_titolari"],
)
def test_formazione_parziale_salvata_ma_resta_probabili(sessione, arrivate):
    prepara(sessione)
    adesso = INIZIO - timedelta(minutes=30)
    fonte = FonteFinta(formazioni_uscite={100: arrivate})
    assert pre_partita.esegui(sessione, fonte, adesso) == 0
    assert sessione.get(Partita, 100).stato_formazioni == "probabili"
    righe = sessione.scalars(select(Formazione).where(Formazione.tipo == "ufficiale")).all()
    assert sorted(f.giocatore_id for f in righe) == [1, 2]
    # al controllo successivo arrivano entrambe: ufficiali, e le righe non si duplicano
    fonte = FonteFinta(formazioni_uscite=ufficiali())
    assert pre_partita.esegui(sessione, fonte, adesso + timedelta(minutes=10)) == 1
    assert sessione.get(Partita, 100).stato_formazioni == "ufficiali"
    righe = sessione.scalars(select(Formazione).where(Formazione.tipo == "ufficiale")).all()
    assert sorted(f.giocatore_id for f in righe) == [1, 2, 5]


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
    assert sorted((f.squadra_id, f.giocatore_id, f.griglia) for f in probabili) == [
        (1, 3, "2:1"), (2, 6, "2:1"),
    ]


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
    for nome in ("API_FOOTBALL_KEY", "FOOTBALL_DATA_KEY", "FONTE_DATI", "STORICO_MAX_MINUTI"):
        monkeypatch.delenv(nome, raising=False)  # mai rete ne' chiavi vere nei test
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


def test_main_api_football_senza_chiave_restituisce_2(db_file, monkeypatch, caplog):
    monkeypatch.setenv("FONTE_DATI", "api_football")
    with caplog.at_level(logging.ERROR):
        assert pre_partita.main([]) == 2
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert notte.main([]) == 2


def test_main_espn_senza_nessuna_chiave_non_esce_con_2(db_file, monkeypatch):
    """Con ESPN (default) non serve la chiave API-Football: i job partono (qui con fonti finte)."""
    monkeypatch.delenv("FONTE_DATI", raising=False)
    monkeypatch.delenv("FOOTBALL_DATA_KEY", raising=False)
    dentro_db(db_file, lambda s: prepara(s, data=datetime.now(timezone.utc) + timedelta(minutes=30)))
    fonte = FonteFinta(formazioni_uscite=ufficiali())
    assert pre_partita.main([], crea_fonte=lambda s, priorita: fonte) == 0
    assert fonte.chiamate == [("formazioni", 100)]
    assert notte.main(
        [], crea_fonte=lambda s, priorita: FonteFinta(partite_ft=1), controllo=lambda f: []
    ) == 0


def test_main_pre_partita_senza_partite_nessuna_chiamata(db_file):
    dentro_db(db_file, lambda s: prepara(s, data=datetime.now(timezone.utc) + timedelta(hours=5)))
    fonte = FonteFinta()
    assert pre_partita.main([], crea_fonte=lambda s, priorita: fonte) == 0
    assert fonte.chiamate == []


def test_main_pre_partita_salva_ufficiali(db_file):
    dentro_db(db_file, lambda s: prepara(s, data=datetime.now(timezone.utc) + timedelta(minutes=30)))
    fonte = FonteFinta(formazioni_uscite=ufficiali())
    assert pre_partita.main([], crea_fonte=lambda s, priorita: fonte) == 0
    assert fonte.chiamate == [("formazioni", 100)]

    def controlla(s):
        assert s.get(Partita, 100).stato_formazioni == "ufficiali"

    dentro_db(db_file, controlla)


def test_main_notte_usa_due_fonti_e_restituisce_0(db_file):
    richieste = []

    def crea(s, priorita):
        richieste.append(priorita)
        return FonteFinta(partite_ft=2)

    assert notte.main([], crea_fonte=crea, controllo=lambda f: []) == 0
    assert richieste == [Priorita.OGGI, Priorita.STORICO]


def test_main_notte_api_football_usa_la_chiave_e_un_solo_limite(db_file, monkeypatch):
    monkeypatch.setenv("FONTE_DATI", "api_football")
    monkeypatch.setenv("API_FOOTBALL_KEY", "chiave-di-prova")
    fonti = []

    def crea(s, priorita):
        fonte = comune.crea_fonte(s, priorita)
        fonti.append(fonte)
        return FonteFinta(partite_ft=1)

    assert notte.main([], crea_fonte=crea) == 0  # niente controllo di salute (non ESPN)
    assert all(isinstance(f, ApiFootball) for f in fonti)
    assert [f.priorita for f in fonti] == [Priorita.OGGI, Priorita.STORICO]
    assert isinstance(fonti[0].limite, LimiteRichieste) and fonti[0].limite is fonti[1].limite


def test_crea_fonte_predefinita_espn_senza_chiavi(sessione, monkeypatch):
    for nome in ("FONTE_DATI", "API_FOOTBALL_KEY"):
        monkeypatch.delenv(nome, raising=False)
    fonte = comune.crea_fonte(sessione, Priorita.STORICO)
    assert isinstance(fonte, Espn)
    assert fonte.priorita is Priorita.STORICO
    assert (fonte.limite.max_minuto, fonte.limite.max_giorno) == (30, 5000)
    # lo stesso limite per tutte le fonti del processo (ritmo al minuto condiviso)
    assert comune.crea_fonte(sessione, Priorita.OGGI).limite is fonte.limite
    fonte.client.close()


def test_crea_fonte_variabile_vuota_vale_espn(sessione, monkeypatch):
    monkeypatch.setenv("FONTE_DATI", "")
    fonte = comune.crea_fonte(sessione, Priorita.OGGI)
    assert isinstance(fonte, Espn)
    fonte.client.close()


def test_crea_fonte_api_football_con_limite_e_chiave(sessione, monkeypatch):
    monkeypatch.setenv("FONTE_DATI", "api_football")
    monkeypatch.setenv("API_FOOTBALL_KEY", "k")
    monkeypatch.setenv("API_RICHIESTE_GIORNO", "7500")
    fonte = comune.crea_fonte(sessione, Priorita.OGGI)
    assert isinstance(fonte, ApiFootball)
    assert fonte.limite.max_giorno == 7500
    fonte.client.close()


def test_crea_fonte_api_football_senza_chiave(sessione, monkeypatch):
    monkeypatch.setenv("FONTE_DATI", "api_football")
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    with pytest.raises(comune.ErroreConfigurazione, match="API-Football"):
        comune.crea_fonte(sessione, Priorita.OGGI)


def test_crea_fonte_memorizza_la_fonte_del_database_vuoto(sessione, monkeypatch):
    from ammonizioni.db import repo

    monkeypatch.setenv("FONTE_DATI", "api_football")
    monkeypatch.setenv("API_FOOTBALL_KEY", "k")
    comune.crea_fonte(sessione, Priorita.OGGI).client.close()
    assert repo.leggi_impostazione(sessione, "fonte_dati_db") == "api_football"
    monkeypatch.setenv("FONTE_DATI", "espn")
    with pytest.raises(comune.ErroreConfigurazione, match="contiene dati di api_football"):
        comune.crea_fonte(sessione, Priorita.OGGI)


def test_crea_fonte_espn_poi_api_football_rifiutata(sessione, monkeypatch):
    monkeypatch.delenv("FONTE_DATI", raising=False)
    comune.crea_fonte(sessione, Priorita.OGGI).client.close()
    monkeypatch.setenv("FONTE_DATI", "api_football")
    monkeypatch.setenv("API_FOOTBALL_KEY", "k")
    with pytest.raises(comune.ErroreConfigurazione, match="database nuovo e vuoto"):
        comune.crea_fonte(sessione, Priorita.OGGI)


def test_crea_fonte_database_con_partite_senza_valore_e_espn(sessione, monkeypatch):
    """Un database creato prima del controllo (partite, nessun valore) si considera ESPN."""
    prepara(sessione)
    monkeypatch.setenv("FONTE_DATI", "api_football")
    monkeypatch.setenv("API_FOOTBALL_KEY", "k")
    with pytest.raises(comune.ErroreConfigurazione, match="contiene dati di espn"):
        comune.crea_fonte(sessione, Priorita.OGGI)
    monkeypatch.delenv("FONTE_DATI")
    comune.crea_fonte(sessione, Priorita.OGGI).client.close()


def test_job_escono_con_2_se_la_fonte_non_e_quella_del_database(db_file, monkeypatch, caplog):
    from ammonizioni.db import repo

    dentro_db(db_file, lambda s: repo.scrivi_impostazione(s, "fonte_dati_db", "api_football"))
    monkeypatch.delenv("FONTE_DATI", raising=False)
    with caplog.at_level(logging.ERROR):
        assert pre_partita.main([]) == 2
        assert notte.main([]) == 2
    assert "database nuovo e vuoto" in caplog.text


def test_crea_football_data_con_e_senza_chiave(sessione, monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_KEY", raising=False)
    senza = comune.crea_football_data(sessione)
    assert isinstance(senza, FootballData) and not senza.chiave
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "fd")
    con = comune.crea_football_data(sessione)
    assert con.chiave == "fd"
    assert con.limite is senza.limite  # uno solo per processo: 10 richieste al minuto
    assert (con.limite.max_minuto, con.limite.sessione) == (10, None)  # non tocca il DB


def test_crea_api_football_usa_il_limite_dato(sessione):  # fabbrica usata da crea_fonte
    limite = LimiteRichieste(sessione)
    fonte = comune.crea_api_football("k", Priorita.STORICO, limite)
    assert isinstance(fonte, ApiFootball)
    assert fonte.limite is limite and fonte.priorita is Priorita.STORICO
    fonte.client.close()


def test_main_notte_errore_sul_calendario_poi_storico(db_file, monkeypatch):
    from ammonizioni.fonti.base import ErroreFonte

    class CalendarioRotto(FonteFinta):
        def partite(self, competizione_id, stagione):
            if (competizione_id, stagione) == (135, 2026):
                self._chiamata("partite", competizione_id, stagione)
                raise ErroreFonte("calendario rotto")
            return super().partite(competizione_id, stagione)

    fonti = []

    def crea(s, priorita):
        fonti.append(CalendarioRotto())
        return fonti[-1]

    assert notte.main([], crea_fonte=crea, controllo=lambda f: []) == 0
    assert len(fonti) == 2
    # lo storico ha scaricato i suoi calendari: 7 competizioni x 3 stagioni, meno i due
    # campionati della stagione corrente (sono del job notturno)
    assert len(fonti[1].chiamate) == 19

    def controlla(s):
        assert s.get(UltimoAggiornamento, "notte").completo is False
        assert s.get(UltimoAggiornamento, "storico") is not None

    dentro_db(db_file, controlla)


def test_main_notte_con_limite_raggiunto_restituisce_0(db_file):
    assert notte.main(
        [], crea_fonte=lambda s, p: FonteFinta(partite_ft=3, limite_dopo=1), controllo=lambda f: []
    ) == 0
