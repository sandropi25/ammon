import pytest
from costruttori import medie_standard

from ammonizioni.motore.fattori.arbitro import fattore_arbitro, inclinazione_con_squadra
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import StatArbitro


def _arbitro(partite=20, gialli=5.4, falli=25.0, con=None):
    return StatArbitro("Rossi", partite, gialli, falli, con or {})


def test_arbitro_severo_alza_e_motiva():
    f = fattore_arbitro(_arbitro(), 1, medie_standard(), Pesi())
    assert f.nome == "arbitro"
    assert f.valore > 1
    assert f.motivazione == "arbitro da 5,4 gialli"
    assert f.n_dati == 20


def test_arbitro_con_4_partite_resta_vicino_a_1():
    pieno = fattore_arbitro(_arbitro(partite=20), 1, medie_standard(), Pesi())
    poco = fattore_arbitro(_arbitro(partite=4), 1, medie_standard(), Pesi())
    assert abs(poco.valore - 1) <= 0.2 * abs(pieno.valore - 1) + 1e-9
    assert poco.valore > 1


def test_arbitro_assente_fattore_1():
    f = fattore_arbitro(None, 1, medie_standard(), Pesi())
    assert f.valore == 1.0
    assert f.motivazione is None
    assert f.n_dati == 0


def test_arbitro_tanti_falli_pochi_gialli():
    f = fattore_arbitro(_arbitro(gialli=3.5, falli=30.0), 1, medie_standard(), Pesi())
    assert f.motivazione == "arbitro: tanti falli, pochi gialli"


def test_arbitro_nella_media_nessuna_motivazione():
    f = fattore_arbitro(_arbitro(gialli=4.2, falli=25.0), 1, medie_standard(), Pesi())
    assert f.valore == 1.0
    assert f.motivazione is None


def test_arbitro_storia_con_la_squadra_alza_con_almeno_2_partite():
    base = fattore_arbitro(_arbitro(), 1, medie_standard(), Pesi())
    con = fattore_arbitro(_arbitro(con={1: (7.0, 3)}), 1, medie_standard(), Pesi())
    assert con.valore > base.valore
    una = fattore_arbitro(_arbitro(con={1: (7.0, 1)}), 1, medie_standard(), Pesi())
    assert una.valore == base.valore


def test_arbitro_con_la_squadra_ristretto_verso_1():
    # 7 gialli con la squadra contro 5,4 di media: rapporto 1,296
    due = inclinazione_con_squadra(_arbitro(con={1: (7.0, 2)}), 1)
    otto = inclinazione_con_squadra(_arbitro(con={1: (7.0, 8)}), 1)
    assert due == pytest.approx(1 + (7.0 / 5.4 - 1) * 2 / 10)
    assert otto == pytest.approx(1 + (7.0 / 5.4 - 1) * 0.5)
    assert 1 < due < otto < 7.0 / 5.4
    assert inclinazione_con_squadra(_arbitro(con={1: (7.0, 1)}), 1) == 1.0
    assert inclinazione_con_squadra(_arbitro(), 1) == 1.0
    assert inclinazione_con_squadra(None, 1) == 1.0
    # anche verso il basso: con la squadra ammonisce meno, ma non a pieno
    meno = inclinazione_con_squadra(_arbitro(con={1: (3.0, 4)}), 1)
    assert 3.0 / 5.4 < meno < 1


def test_arbitro_valore_limitato():
    f = fattore_arbitro(_arbitro(gialli=20.0), 1, medie_standard(), Pesi())
    assert f.valore == Pesi().limiti_fattore[1]
