from datetime import date, datetime, timedelta, timezone

import pytest

from ammonizioni.db.modelli import ContatoreRichieste
from ammonizioni.fonti import limite as modulo_limite
from ammonizioni.fonti.limite import LimiteRichieste, LimiteSuperato, Priorita


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def avanza(self, secondi):
        self.t += secondi


def oggi_utc() -> date:
    return datetime.now(timezone.utc).date()


def test_storico_non_tocca_la_riserva(sessione):
    l = LimiteRichieste(sessione, max_giorno=100, riserva_oggi=30, dormi=lambda s: None)
    for _ in range(70):
        l.prendi(Priorita.STORICO)
    with pytest.raises(LimiteSuperato):
        l.prendi(Priorita.STORICO)
    l.prendi(Priorita.OGGI)  # la riserva è ancora disponibile


def test_oggi_si_ferma_a_max_giorno(sessione):
    l = LimiteRichieste(sessione, max_giorno=5, riserva_oggi=2, dormi=lambda s: None)
    for _ in range(5):
        l.prendi(Priorita.OGGI)
    assert l.rimanenti(Priorita.OGGI) == 0
    with pytest.raises(LimiteSuperato):
        l.prendi(Priorita.OGGI)
    assert sessione.get(ContatoreRichieste, oggi_utc()).usate == 5


def test_rimanenti(sessione):
    l = LimiteRichieste(sessione, max_giorno=100, riserva_oggi=30, dormi=lambda s: None)
    assert l.rimanenti(Priorita.OGGI) == 100
    assert l.rimanenti(Priorita.STORICO) == 70
    l.prendi(Priorita.OGGI)
    assert l.rimanenti(Priorita.OGGI) == 99
    assert l.rimanenti(Priorita.STORICO) == 69


def test_undicesima_richiesta_nel_minuto_attende(sessione):
    attese = []
    t = FakeClock()
    l = LimiteRichieste(
        sessione, orologio=t, dormi=lambda s: (attese.append(s), t.avanza(s))
    )
    for _ in range(11):
        l.prendi(Priorita.OGGI)
    assert attese and attese[0] > 0
    assert len(attese) == 1
    assert attese[0] == pytest.approx(60)


def test_nessuna_attesa_con_richieste_distanziate(sessione):
    attese = []
    t = FakeClock()
    l = LimiteRichieste(sessione, orologio=t, dormi=attese.append)
    for _ in range(25):
        l.prendi(Priorita.OGGI)
        t.avanza(7)  # 8-9 richieste al minuto
    assert attese == []


def test_richiesta_negata_non_incrementa_ne_attende(sessione):
    attese = []
    l = LimiteRichieste(sessione, max_giorno=1, riserva_oggi=0, dormi=attese.append)
    l.prendi(Priorita.OGGI)
    with pytest.raises(LimiteSuperato):
        l.prendi(Priorita.OGGI)
    assert attese == []
    assert sessione.get(ContatoreRichieste, oggi_utc()).usate == 1


def test_contatore_persistito_e_azzerato_il_giorno_dopo(sessione):
    giorno = [date(2026, 11, 4)]
    l = LimiteRichieste(
        sessione, max_giorno=3, riserva_oggi=0, dormi=lambda s: None,
        oggi=lambda: giorno[0],
    )
    for _ in range(3):
        l.prendi(Priorita.OGGI)
    assert sessione.get(ContatoreRichieste, date(2026, 11, 4)).usate == 3

    # una nuova istanza (nuova esecuzione) legge il contatore dal DB
    l2 = LimiteRichieste(
        sessione, max_giorno=3, riserva_oggi=0, dormi=lambda s: None,
        oggi=lambda: giorno[0],
    )
    assert l2.rimanenti(Priorita.OGGI) == 0
    with pytest.raises(LimiteSuperato):
        l2.prendi(Priorita.OGGI)

    giorno[0] = giorno[0] + timedelta(days=1)
    assert l2.rimanenti(Priorita.OGGI) == 3
    l2.prendi(Priorita.OGGI)
    assert sessione.get(ContatoreRichieste, date(2026, 11, 5)).usate == 1
    assert sessione.get(ContatoreRichieste, date(2026, 11, 4)).usate == 3


def test_giorno_predefinito_del_contatore_e_quello_utc(sessione, monkeypatch):
    """Alle 00:30 ora di Roma del 2 gennaio in UTC e' ancora il 1° gennaio: il contatore
    (che si azzera con la quota di API-Football, a mezzanotte UTC) e' del 1° gennaio."""

    class OrologioFinto(datetime):
        @classmethod
        def now(cls, tz=None):
            utc = datetime(2030, 1, 1, 23, 30, tzinfo=timezone.utc)
            return utc.astimezone(tz) if tz is not None else datetime(2030, 1, 2, 0, 30)

    monkeypatch.setattr(modulo_limite, "datetime", OrologioFinto, raising=False)
    l = LimiteRichieste(sessione, dormi=lambda s: None)
    l.prendi(Priorita.OGGI)
    assert sessione.get(ContatoreRichieste, date(2030, 1, 1)).usate == 1
    assert sessione.get(ContatoreRichieste, date(2030, 1, 2)) is None
