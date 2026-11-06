"""Orchestratore con orologio iniettato e fonti finte: nessuna rete, nessun database reale."""
from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest
from conftest import FonteFinta, partita_dati
from sqlalchemy.orm import Session

from ammonizioni.caricamento import notturno
from ammonizioni.caricamento.biografie import RiepilogoBio
from ammonizioni.db import repo
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Giocata, Giocatore, Partita
from ammonizioni.giocate.registro import aggiungi_giocata
from ammonizioni.scheduler import orchestratore

UTC = timezone.utc
# 12 settembre 2026 (ora legale, UTC+2): partita alle 15:00 italiane = 13:00 UTC
PARTITA_15 = datetime(2026, 9, 12, 13, 0, tzinfo=UTC)


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'orch.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    for nome in ("API_FOOTBALL_KEY", "FOOTBALL_DATA_KEY", "FONTE_DATI", "STORICO_MAX_MINUTI"):
        monkeypatch.delenv(nome, raising=False)
    engine = modulo_sessione.crea_engine(url)
    modulo_sessione.crea_tabelle(engine)
    engine.dispose()
    return url


@contextmanager
def db(url):
    engine = modulo_sessione.crea_engine(url)
    try:
        with Session(engine) as s:
            yield s
    finally:
        engine.dispose()


def semina(url, *partite):
    with db(url) as s:
        for p in partite:
            notturno.salva_partita(s, p)
        s.commit()


class Lancio:
    """Lancia main() con orologio e fonti finte e ricorda quante fonti sono state create."""

    def __init__(self, calendari):
        self.calendari = calendari
        self.fonti = []
        self.bio = 0

    def _crea(self, s, priorita):
        self.fonti.append(FonteFinta(calendari=self.calendari))
        return self.fonti[-1]

    def _bio(self, s):
        self.bio += 1
        return RiepilogoBio()

    def __call__(self, quando):
        return orchestratore.main(
            [], crea_fonte=self._crea, crea_fd=lambda s: None, controllo=lambda f: [],
            biografie=self._bio, orologio=lambda: quando,
        )

    @property
    def richieste(self):
        return sum(len(f.chiamate) for f in self.fonti)


def calendario_giorno(stato="NS", id=10, quando=PARTITA_15):
    return {(135, 2026): [partita_dati(id, quando, stato=stato, arbitro=None)]}


# --- decisione ---------------------------------------------------------------


def test_aggiornamento_giornata_solo_fra_6_e_7_ore_prima_della_prima_partita(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"))
    with db(db_file) as s:
        # 05:05 UTC = 07:05 italiane: mancano 7h55, troppo presto
        assert orchestratore.decidi(s, datetime(2026, 9, 12, 5, 5, tzinfo=UTC)).niente
        # 06:05 UTC = 08:05 italiane: nella finestra 08:00-09:00
        d = orchestratore.decidi(s, datetime(2026, 9, 12, 6, 5, tzinfo=UTC))
        assert d.giornata == date(2026, 9, 12)


def test_giorno_con_partita_alle_15_aggiorna_una_volta_sola_alle_08(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"))
    lancio = Lancio(calendario_giorno())
    # prima della finestra: nessuna fonte, nessuna richiesta
    assert lancio(datetime(2026, 9, 12, 5, 5, tzinfo=UTC)) == 0
    assert lancio.fonti == []
    # 08:05 italiane: aggiornamento della giornata
    assert lancio(datetime(2026, 9, 12, 6, 5, tzinfo=UTC)) == 0
    assert len(lancio.fonti) == 2 and lancio.richieste > 0 and lancio.bio == 1
    with db(db_file) as s:
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_GIORNATA) == "2026-09-12"
    fatte = (len(lancio.fonti), lancio.richieste)
    # ora dopo, ora dopo ancora, e tardi: niente di nuovo
    for ora in (7, 8, 11):
        assert lancio(datetime(2026, 9, 12, ora, 5, tzinfo=UTC)) == 0
    assert (len(lancio.fonti), lancio.richieste) == fatte


def test_giornata_crea_le_probabili_formazioni_delle_partite_di_oggi(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"))
    # una partita di ieri con le presenze: l'ultimo XI
    lancio = Lancio(
        {(135, 2026): [partita_dati(10, PARTITA_15, stato="NS", arbitro=None),
                       partita_dati(9, datetime(2026, 9, 5, 13, 0, tzinfo=UTC), arbitro=None)]}
    )
    lancio(datetime(2026, 9, 12, 6, 5, tzinfo=UTC))
    with db(db_file) as s:
        from ammonizioni.db.modelli import Formazione
        assert s.query(Formazione).filter_by(partita_id=10, tipo="probabile").count() > 0


def test_giorno_senza_partite_non_fa_nulla(db_file):
    lancio = Lancio({})
    for ora in range(0, 24):
        assert lancio(datetime(2026, 9, 14, ora, 5, tzinfo=UTC)) == 0
    assert lancio.fonti == [] and lancio.richieste == 0


def test_database_vuoto_non_fa_nulla(db_file):
    lancio = Lancio({})
    assert lancio(datetime(2026, 9, 12, 6, 5, tzinfo=UTC)) == 0
    assert lancio.fonti == []


def test_partita_rinviata_non_conta_come_prima_partita(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="PST", arbitro=None))
    with db(db_file) as s:
        assert orchestratore.decidi(s, datetime(2026, 9, 12, 6, 5, tzinfo=UTC)).niente


def test_cron_saltato_recupera_fino_a_3_ore_prima(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"))
    with db(db_file) as s:
        # 09:05 UTC = 11:05 italiane: la finestra e' passata ma mancano ancora 3h55
        assert orchestratore.decidi(s, datetime(2026, 9, 12, 9, 5, tzinfo=UTC)).giornata
        # 10:05 UTC: mancano meno di 3 ore, troppo tardi
        assert orchestratore.decidi(s, datetime(2026, 9, 12, 10, 5, tzinfo=UTC)).niente


def test_giorno_del_cambio_ora_legale_finestra_alle_08_italiane(db_file):
    """25 ottobre 2026: si torna all'ora solare (UTC+1 dalle 03:00). 15:00 italiane = 14:00 UTC."""
    partita = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)
    semina(db_file, partita_dati(10, partita, stato="NS"))
    with db(db_file) as s:
        assert orchestratore.decidi(s, datetime(2026, 10, 25, 6, 5, tzinfo=UTC)).niente  # 07:05
        d = orchestratore.decidi(s, datetime(2026, 10, 25, 7, 5, tzinfo=UTC))  # 08:05 italiane
        assert d.giornata == date(2026, 10, 25)


def test_giorno_italiano_dura_25_ore_nel_cambio_ora():
    inizio, fine = orchestratore._limiti_giorno(date(2026, 10, 25))
    assert (fine - inizio).total_seconds() == 25 * 3600
    assert inizio == datetime(2026, 10, 24, 22, 0, tzinfo=UTC)


def test_partita_di_mezzanotte_italiana_appartiene_al_giorno_italiano(db_file):
    """23:30 UTC del 12 settembre = 01:30 italiane del 13: non e' una partita del 12."""
    semina(db_file, partita_dati(10, datetime(2026, 9, 12, 23, 30, tzinfo=UTC), stato="NS"))
    with db(db_file) as s:
        assert orchestratore.partite_del_giorno(s, date(2026, 9, 12)) == []
        assert [p.id for p in orchestratore.partite_del_giorno(s, date(2026, 9, 13))] == [10]


# --- chiusura ----------------------------------------------------------------


def test_chiusura_due_ore_dopo_la_fine_e_senza_doppioni(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"))
    with db(db_file) as s:
        s.add(Giocatore(id=1001, nome="Giocatore 10"))
        giocata = aggiungi_giocata(s, 10, 1001, "Tipster", 3.0, 10.0, date(2026, 9, 12))
        s.commit()
        giocata_id = giocata.id
    lancio = Lancio(calendario_giorno(stato="FT"))
    # inizio 13:00 UTC, fine stimata 15:00, chiusura dalle 17:00: alle 16:05 ancora niente
    with db(db_file) as s:
        repo.scrivi_impostazione(s, orchestratore.CHIAVE_GIORNATA, "2026-09-12")
        s.commit()
    assert lancio(datetime(2026, 9, 12, 16, 5, tzinfo=UTC)) == 0
    assert lancio.fonti == []
    # 17:05 UTC: chiusura
    assert lancio(datetime(2026, 9, 12, 17, 5, tzinfo=UTC)) == 0
    assert len(lancio.fonti) == 1 and lancio.bio == 0
    with db(db_file) as s:
        assert s.get(Partita, 10).statistiche_scaricate is True
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_CHIUSE) == [10]
        assert s.get(Giocata, giocata_id).esito == "vinta"  # il giocatore 1001 ha 1 giallo
    fatte = lancio.richieste
    # i controlli successivi non rifanno nulla
    for ora in (18, 19, 23):
        assert lancio(datetime(2026, 9, 12, ora, 5, tzinfo=UTC)) == 0
    assert lancio.richieste == fatte and len(lancio.fonti) == 1


def test_chiusura_con_statistiche_vuote_riprova_poi_si_arrende(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"))
    with db(db_file) as s:
        repo.scrivi_impostazione(s, orchestratore.CHIAVE_GIORNATA, "2026-09-12")
        s.commit()
    chiamate = []

    class Vuota(FonteFinta):
        def statistiche(self, partita_id):
            chiamate.append(partita_id)
            return []

    lancio = Lancio(calendario_giorno(stato="FT"))
    lancio._crea = lambda s, p: lancio.fonti.append(Vuota(calendari=lancio.calendari)) or lancio.fonti[-1]
    lancio(datetime(2026, 9, 12, 17, 5, tzinfo=UTC))
    with db(db_file) as s:
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_CHIUSE) == []  # riprova
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_TENTATIVI) == {"10": 1}
    for ora in range(18, 18 + orchestratore.TENTATIVI_CHIUSURA_MAX):
        lancio(datetime(2026, 9, 12, ora, 5, tzinfo=UTC))
    with db(db_file) as s:
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_CHIUSE) == [10]
    n = len(lancio.fonti)
    lancio(datetime(2026, 9, 13, 3, 5, tzinfo=UTC))
    assert len(lancio.fonti) == n  # chiusa: non si riprova piu'


def test_partita_rinviata_dopo_il_calendario_viene_chiusa_senza_statistiche(db_file):
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"))
    with db(db_file) as s:
        repo.scrivi_impostazione(s, orchestratore.CHIAVE_GIORNATA, "2026-09-12")
        s.commit()
    lancio = Lancio(calendario_giorno(stato="PST"))
    lancio(datetime(2026, 9, 12, 17, 5, tzinfo=UTC))
    with db(db_file) as s:
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_CHIUSE) == [10]
        assert s.get(Partita, 10).statistiche_scaricate is False


def test_partite_vecchie_di_oltre_7_giorni_restano_allo_storico(db_file):
    semina(db_file, partita_dati(10, datetime(2026, 9, 1, 13, 0, tzinfo=UTC)))
    with db(db_file) as s:
        assert orchestratore.partite_da_chiudere(s, datetime(2026, 9, 12, 17, 5, tzinfo=UTC)) == []


def test_giornata_e_chiusura_nella_stessa_esecuzione(db_file):
    """Prima partita alle 15:00 (aggiornamento alle 08:05) e una di ieri ancora da chiudere."""
    ieri = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)
    semina(db_file, partita_dati(10, PARTITA_15, stato="NS"), partita_dati(9, ieri, stato="FT"))
    lancio = Lancio({(135, 2026): [
        partita_dati(10, PARTITA_15, stato="NS", arbitro=None),
        partita_dati(9, ieri, stato="FT", arbitro=None),
    ]})
    assert lancio(datetime(2026, 9, 12, 6, 5, tzinfo=UTC)) == 0
    with db(db_file) as s:
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_GIORNATA) == "2026-09-12"
        assert repo.leggi_impostazione(s, orchestratore.CHIAVE_CHIUSE) == [9]
        assert s.get(Partita, 9).statistiche_scaricate is True


# --- workflow GitHub -----------------------------------------------------------


def _workflow(nome):
    from pathlib import Path

    yaml = pytest.importorskip("yaml")
    radice = Path(__file__).resolve().parents[2]
    return yaml.safe_load((radice / ".github" / "workflows" / nome).read_text(encoding="utf-8"))


def test_workflow_orchestratore_orario():
    w = _workflow("orchestratore.yml")
    assert w[True]["schedule"] == [{"cron": "5 * * * *"}]  # "on" e' letto come True da YAML 1.1
    job = w["jobs"]["orchestratore"]
    assert job["timeout-minutes"] == 60
    passo = next(p for p in job["steps"] if "scheduler.orchestratore" in p.get("run", ""))
    assert "DATABASE_URL" in passo["env"]


def test_workflow_notte_una_volta_a_settimana():
    w = _workflow("notte.yml")
    assert w[True]["schedule"] == [{"cron": "0 3 * * 1"}]
