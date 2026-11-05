"""Su Postgres SUM() restituisce Decimal: gli aggregati della pagina Cerca devono diventare
int/float prima di qualsiasi calcolo (per 90', diffida, confronti)."""
from datetime import datetime, timezone
from decimal import Decimal

from ayuda_app import RADICE  # noqa: F401  (mette app/ in sys.path)

import componenti_cerca as cerca


class _Risultato:
    def __init__(self, righe):
        self._righe = righe

    def all(self):
        return self._righe

    def one(self):
        return self._righe[0]


class _SessioneDecimal:
    def __init__(self, righe):
        self._righe = righe

    def execute(self, _):
        return _Risultato(self._righe)


def test_stagioni_da_decimal_sono_int_e_float():
    righe = [(2026, 135, Decimal("2"), Decimal("135"), Decimal("2"), Decimal("0"),
              Decimal("5"), Decimal("3"))]
    (r,) = cerca._stagioni(_SessioneDecimal(righe), 1)
    for valore in (r.presenze, r.minuti, r.gialli, r.rossi, r.falli_commessi, r.falli_subiti):
        assert type(valore) is int
    assert isinstance(r.gialli90, float) and round(r.gialli90, 2) == 1.33
    assert cerca.celle_stagione(r)[-3] == "1,33"


def test_con_arbitro_da_decimal_restituisce_int():
    s = _SessioneDecimal([(Decimal("6"), Decimal("3"))])
    risultato = cerca._con_arbitro(s, 1, 1, datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert risultato == (6, 3) and all(type(v) is int for v in risultato)


def test_aggregati_vuoti_valgono_zero():
    s = _SessioneDecimal([(None, None)])
    assert cerca._con_arbitro(s, 1, 1, datetime(2026, 11, 5, tzinfo=timezone.utc)) == (0, 0)
    assert cerca.per90(3, 0) is None and cerca.testo_per90(None) == "–"
