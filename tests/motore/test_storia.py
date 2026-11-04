import pytest
from costruttori import riga

from ammonizioni.motore.fattori.storia import fattore_storia
from ammonizioni.motore.pesi import Pesi


def test_due_gialli_negli_ultimi_due_derby_alza_storia():
    storico = [
        riga(avversario_id=50, rivalita=True, gialli=1),
        riga(avversario_id=51, rivalita=True, gialli=1),
    ]
    f = fattore_storia(storico, 99, True, [], tasso_base90=0.2, pesi=Pesi())
    assert f.nome == "storia"
    assert f.valore > 1
    assert f.motivazione == "Ammonito negli ultimi 2 derby"
    assert f.n_dati == 2


def test_un_solo_precedente_resta_vicino_a_1():
    storico = [riga(avversario_id=7, gialli=1)]
    f = fattore_storia(storico, 7, False, [], tasso_base90=0.2, pesi=Pesi())
    # r = 5, f grezzo = 1 + 0,3*4 = 2,2 attenuato a 1 + 1,2*0,2 = 1,24
    assert f.valore == pytest.approx(1.24)
    assert f.motivazione is None
    assert f.n_dati == 1


def test_storia_con_altra_maglia_conta():
    storico = [
        riga(squadra_id=10, avversario_id=7, gialli=1),
        riga(squadra_id=11, avversario_id=7, gialli=1),
    ]
    f = fattore_storia(storico, 7, False, [], tasso_base90=0.2, pesi=Pesi())
    assert f.valore > 1.5
    assert f.motivazione.startswith("2 gialli in 2 partite contro")


def test_motivazione_usa_nome_avversario():
    storico = [riga(avversario_id=7, gialli=1), riga(avversario_id=7, gialli=1)]
    f = fattore_storia(
        storico, 7, False, [], tasso_base90=0.2, pesi=Pesi(), nome_avversario="Inter"
    )
    assert f.motivazione == "2 gialli in 2 partite contro Inter"


def test_tasso_base_nullo_da_fattore_neutro():
    f = fattore_storia([riga(avversario_id=7, gialli=1)], 7, False, [], 0.0, Pesi())
    assert (f.nome, f.valore, f.motivazione, f.n_dati) == ("storia", 1.0, None, 0)


def test_righe_con_zero_minuti_escluse():
    storico = [
        riga(avversario_id=7, gialli=0, minuti=0),
        riga(avversario_id=7, gialli=0, minuti=0),
    ]
    f = fattore_storia(storico, 7, False, [], tasso_base90=0.2, pesi=Pesi())
    assert f.valore == 1.0
    assert f.motivazione is None
    assert f.n_dati == 0


def test_gia_ammonito_contro_avversario_diretto():
    s1 = riga(squadra_id=1, avversario_id=20, gialli=1)
    s2 = riga(squadra_id=1, avversario_id=21, gialli=1)
    diretto = [
        riga(partita_id=s1.partita_id, squadra_id=2, avversario_id=1),
        riga(partita_id=s2.partita_id, squadra_id=2, avversario_id=1),
    ]
    f = fattore_storia(
        [s1, s2], 99, False, diretto, 0.2, Pesi(), nome_avv_diretto="Rossi"
    )
    assert f.valore > 1
    assert f.motivazione == "già ammonito contro Rossi"
    assert f.n_dati == 2


def test_stessa_squadra_nello_storico_diretto_non_e_duello():
    s1 = riga(squadra_id=1, avversario_id=20, gialli=1)
    s2 = riga(squadra_id=1, avversario_id=21, gialli=1)
    diretto = [
        riga(partita_id=s1.partita_id, squadra_id=1),
        riga(partita_id=s2.partita_id, squadra_id=1),
    ]
    f = fattore_storia([s1, s2], 99, False, diretto, 0.2, Pesi())
    assert f.valore == 1.0
    assert f.n_dati == 0


def test_derby_non_consecutivi_ripiegano_sul_sottoinsieme_successivo():
    # derby: il piu' recente senza giallo -> k = 0; contro l'avversario c'e' un giallo
    storico = [
        riga(avversario_id=7, rivalita=True, gialli=1),
        riga(avversario_id=7, rivalita=True, gialli=0),
    ]
    f = fattore_storia(
        storico, 7, True, [], 0.2, Pesi(), nome_avversario="Inter"
    )
    assert f.motivazione == "1 giallo in 2 partite contro Inter"


def test_avversario_diretto_che_non_ha_giocato_non_conta_come_duello():
    s1 = riga(squadra_id=1, avversario_id=20, gialli=1)
    s2 = riga(squadra_id=1, avversario_id=21, gialli=1)
    diretto = [
        riga(partita_id=s1.partita_id, squadra_id=2, minuti=0),
        riga(partita_id=s2.partita_id, squadra_id=2, minuti=0),
    ]
    f = fattore_storia([s1, s2], 99, False, diretto, 0.2, Pesi(), nome_avv_diretto="Rossi")
    assert f.valore == 1.0
    assert f.motivazione is None
    assert f.n_dati == 0


def test_zero_gialli_contro_avversario_nessuna_motivazione():
    storico = [riga(avversario_id=7, gialli=0) for _ in range(3)]
    f = fattore_storia(storico, 7, False, [], 0.2, Pesi(), nome_avversario="Inter")
    assert f.motivazione is None


def test_n_dati_conta_partite_distinte_nell_unione():
    storico = [
        riga(avversario_id=7, rivalita=True, gialli=1),
        riga(avversario_id=7, rivalita=False, gialli=0),
        riga(avversario_id=8, rivalita=True, gialli=1),
    ]
    f = fattore_storia(storico, 7, True, [], 0.2, Pesi())
    assert f.n_dati == 3
