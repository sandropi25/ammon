"""Su Postgres SUM() restituisce Decimal (SUM di bigint, SUM di una SUM): le medie del
campionato devono comunque essere float, altrimenti i fattori (float / Decimal) vanno in errore."""
from decimal import Decimal

from ammonizioni.motore.dati import _medie_campionato, _totali_partite
from ammonizioni.motore.fattori.contesto import fattore_contesto
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import ContestoInfo
from datetime import datetime, timezone


class _Risultato:
    def __init__(self, righe):
        self._righe = righe

    def one(self):
        return self._righe[0]

    def all(self):
        return self._righe


class _SessioneDecimal:
    """Sessione finta che risponde come Postgres: i totali sono Decimal."""

    def __init__(self):
        self._risposte = [
            _Risultato([(10, Decimal("45"), Decimal("260"))]),
            _Risultato([
                ("D", Decimal("900"), Decimal("20"), Decimal("120"), Decimal("80"),
                 Decimal("30"), Decimal("5"), Decimal("600.5"), 100),
                ("M", Decimal("900"), Decimal("30"), Decimal("110"), Decimal("90"),
                 Decimal("60"), Decimal("20"), Decimal("610.0"), 100),
            ]),
        ]

    def execute(self, _):
        return self._risposte.pop(0)


def test_medie_campionato_con_decimal_sono_float():
    medie = _medie_campionato(_SessioneDecimal(), 2026, datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert isinstance(medie.gialli_partita, float) and medie.gialli_partita == 4.5
    assert isinstance(medie.falli_partita, float) and medie.falli_partita == 26.0
    for m in medie.per_ruolo.values():
        for valore in (m.gialli90, m.falli90, m.falli_subiti90, m.dribbling90, m.ga90):
            assert isinstance(valore, float)


def test_fattore_contesto_con_medie_da_decimal_non_solleva():
    medie = _medie_campionato(_SessioneDecimal(), 2026, datetime(2026, 11, 1, tzinfo=timezone.utc))
    ctx = ContestoInfo(
        rivalita=False, campo_caldo=False, posta={}, precedenti_n=4, precedenti_gialli_medi=5.0
    )
    assert fattore_contesto(ctx, 1, medie, Pesi()).valore > 1.0


def test_totali_partite_restituisce_int_anche_da_decimal():
    class S:
        def execute(self, _):
            return _Risultato([(7, Decimal("5"), Decimal("23"))])

    totali = _totali_partite(S(), [7])
    assert totali == {7: (5, 23)}
    assert all(isinstance(v, int) for v in totali[7])
