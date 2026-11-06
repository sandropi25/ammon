"""Cartellini totali di partita (dalle presenze o dal tabellone ESPN) e stagione 2023."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from conftest import FonteFinta, partita_dati
from sqlalchemy import select

from ammonizioni.caricamento import storico, totali
from ammonizioni.caricamento.notturno import salva_partita, scarica_statistiche_partita
from ammonizioni.config import STAGIONI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Arbitro, Giocatore, Partita, Presenza
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.football_data import ArbitroPartita

OGGI = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _dati(id, data, **kw):
    totali_ = {k: kw.pop(k) for k in ("gialli_totali", "rossi_totali", "falli_totali") if k in kw}
    return replace(partita_dati(id, data, **kw), **totali_)


def _totali(s, pid):
    p = s.get(Partita, pid)
    return p.gialli_totali, p.rossi_totali, p.falli_totali


def test_salva_partita_scrive_i_totali_del_tabellone(sessione):
    salva_partita(sessione, _dati(1, OGGI, gialli_totali=4, rossi_totali=1, falli_totali=23))
    sessione.commit()
    assert _totali(sessione, 1) == (4, 1, 23)


def test_totali_non_noti_restano_none_e_non_cancellano_quelli_salvati(sessione):
    salva_partita(sessione, _dati(1, OGGI))
    assert _totali(sessione, 1) == (None, None, None)
    salva_partita(sessione, _dati(1, OGGI, gialli_totali=3, rossi_totali=0, falli_totali=20))
    salva_partita(sessione, _dati(1, OGGI))  # il tabellone non li da' piu': restano
    assert _totali(sessione, 1) == (3, 0, 20)


def test_tabellone_non_sovrascrive_i_totali_delle_presenze(sessione):
    salva_partita(sessione, _dati(1, OGGI))
    sessione.get(Partita, 1).statistiche_scaricate = True
    sessione.get(Partita, 1).gialli_totali = 5
    salva_partita(sessione, _dati(1, OGGI, gialli_totali=2, rossi_totali=0, falli_totali=9))
    assert sessione.get(Partita, 1).gialli_totali == 5


def test_statistiche_scaricate_riempiono_i_totali_dalle_presenze(sessione):
    fonte = FonteFinta(partite_ft=1, due_squadre=True)
    salva_partita(sessione, fonte.partite(135, 2026)[0])
    assert scarica_statistiche_partita(sessione, fonte, 1)
    # un giallo e 3 + 1 falli dalle presenze finte
    assert _totali(sessione, 1) == (1, 0, 4)


def _con_presenze(s, pid, righe):
    """Partita finita con statistiche e presenze (titolare, gialli, rossi, falli)."""
    for n, (titolare, g, r, f) in enumerate(righe):
        gid = pid * 100 + n
        s.merge(Giocatore(id=gid, nome=f"G{gid}"))
        s.flush()
        s.add(Presenza(
            partita_id=pid, giocatore_id=gid, squadra_id=1 + n % 2, titolare=titolare,
            minuti=90 if titolare else 0, gialli=g, rossi=r, falli_commessi=f,
        ))
    s.flush()


def test_riempi_da_presenze_conta_anche_la_panchina(sessione):
    salva_partita(sessione, _dati(1, OGGI))
    salva_partita(sessione, _dati(2, OGGI + timedelta(days=1)))
    salva_partita(sessione, _dati(3, OGGI + timedelta(days=2)))
    for pid in (1, 2):
        sessione.get(Partita, pid).statistiche_scaricate = True
    _con_presenze(sessione, 1, [(True, 1, 0, 3), (True, 0, 1, 2), (False, 1, 0, 0)])
    _con_presenze(sessione, 2, [(True, 0, 0, 1)])
    sessione.commit()
    assert totali.riempi_da_presenze(sessione) == 2
    assert _totali(sessione, 1) == (2, 1, 5)  # il giallo dalla panchina conta
    assert _totali(sessione, 2) == (0, 0, 1)  # zero e' un dato, non "non noto"
    assert _totali(sessione, 3) == (None, None, None)  # senza statistiche resta non noto
    assert totali.riempi_da_presenze(sessione) == 0  # idempotente


def test_riempi_da_presenze_non_tocca_i_totali_gia_presenti(sessione):
    salva_partita(sessione, _dati(1, OGGI, gialli_totali=7, rossi_totali=0, falli_totali=1))
    sessione.get(Partita, 1).statistiche_scaricate = True
    _con_presenze(sessione, 1, [(True, 1, 0, 3)])
    sessione.commit()
    assert totali.riempi_da_presenze(sessione) == 0
    assert _totali(sessione, 1)[0] == 7


# ----------------------------------------------------------------- stagione 2023

class FdFinto:
    def __init__(self, chiave="k", errore=False):
        self.chiave = chiave
        self.errore = errore
        self.chiamate = []

    def arbitri(self, codice, dal, al):
        self.chiamate.append((codice, dal, al))
        if self.errore:
            raise ErroreFonte("403")
        return [
            ArbitroPartita(
                data_utc=datetime(2023, 9, 2, 18, 45, tzinfo=timezone.utc),
                casa="Juventus FC", trasferta="FC Internazionale Milano",
                arbitro_id=1, arbitro_nome="Daniele Doveri", giornata=3,
            )
        ]


def _fonte_2023():
    data = datetime(2023, 9, 2, 18, 45, tzinfo=timezone.utc)
    p = _dati(
        500, data, stagione=2023, arbitro=None, giornata=None, casa=(1, "Juventus"),
        trasferta=(2, "Inter"), gialli_totali=5, rossi_totali=1, falli_totali=26,
    )
    return FonteFinta(calendari={(135, 2023): [p], (140, 2023): []})


def test_stagione_2023_calendario_totali_e_arbitri_senza_statistiche(sessione):
    fonte, fd = _fonte_2023(), FdFinto()
    assert totali.carica_stagione_2023(sessione, fonte, fd) is True
    p = sessione.get(Partita, 500)
    assert (p.stagione, p.gialli_totali, p.rossi_totali, p.falli_totali) == (2023, 5, 1, 26)
    assert p.statistiche_scaricate is False
    assert sessione.scalars(select(Presenza)).first() is None  # nessun giocatore
    assert p.giornata == 3
    assert sessione.get(Arbitro, p.arbitro_id).nome_visualizzato == "Daniele Doveri"
    # una richiesta ESPN per campionato; football-data solo dove ci sono partite da collegare
    assert fonte.chiamate == [("partite", 135, 2023), ("partite", 140, 2023)]
    assert [c[0] for c in fd.chiamate] == ["SA"]
    assert all(c[1:] == (date(2023, 7, 1), date(2024, 6, 30)) for c in fd.chiamate)


def test_stagione_2023_una_tantum(sessione):
    fonte, fd = _fonte_2023(), FdFinto()
    totali.carica_stagione_2023(sessione, fonte, fd)
    chiamate_fonte, chiamate_fd = len(fonte.chiamate), len(fd.chiamate)
    assert totali.carica_stagione_2023(sessione, fonte, fd) is True
    assert (len(fonte.chiamate), len(fd.chiamate)) == (chiamate_fonte, chiamate_fd)
    assert repo.leggi_impostazione(sessione, totali.CALENDARI_2023) == [135, 140]


def test_stagione_2023_errore_arbitri_si_riprova_ma_il_calendario_no(sessione):
    fonte = _fonte_2023()
    assert totali.carica_stagione_2023(sessione, fonte, FdFinto(errore=True)) is False
    assert sessione.get(Partita, 500) is not None
    richieste_espn = len(fonte.chiamate)
    fd = FdFinto()
    assert totali.carica_stagione_2023(sessione, fonte, fd) is True
    assert len(fonte.chiamate) == richieste_espn  # calendario gia' fatto
    assert fd.chiamate  # arbitri riprovati


def test_stagione_2023_senza_chiave_football_data_solo_il_calendario(sessione):
    fonte, fd = _fonte_2023(), FdFinto(chiave=None)
    assert totali.carica_stagione_2023(sessione, fonte, fd) is True
    assert fd.chiamate == []
    assert sessione.get(Partita, 500).arbitro_id is None


def test_stagione_2023_non_entra_nello_storico_delle_statistiche(sessione):
    assert 2023 not in STAGIONI
    fonte, fd = _fonte_2023(), FdFinto()
    storico.avanza(sessione, fonte, fd)
    assert ("statistiche", 500) not in fonte.chiamate
    assert sessione.get(Partita, 500).statistiche_scaricate is False
    assert storico.prossime_da_scaricare(sessione, OGGI) == []


def test_aggregati_decimal_di_postgres_non_rompono_il_riempimento(sessione, monkeypatch):
    """Su Postgres SUM restituisce Decimal: i totali devono diventare int."""
    salva_partita(sessione, _dati(1, OGGI))
    sessione.get(Partita, 1).statistiche_scaricate = True
    _con_presenze(sessione, 1, [(True, 1, 0, 3)])
    sessione.commit()

    class Risultato:
        def all(self):
            return [(1, Decimal("2"), Decimal("1"), Decimal("7"))]

    originale = sessione.execute
    chiamate = []

    def execute(istruzione, *a, **kw):
        if not chiamate:
            chiamate.append(1)
            return Risultato()
        return originale(istruzione, *a, **kw)

    monkeypatch.setattr(sessione, "execute", execute)
    assert totali.riempi_da_presenze(sessione) == 1
    sessione.expire_all()
    p = sessione.get(Partita, 1)
    assert (p.gialli_totali, p.rossi_totali, p.falli_totali) == (2, 1, 7)
    assert isinstance(p.gialli_totali, int)
