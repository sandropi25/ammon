import pytest

from ammonizioni.db.repo import scrivi_impostazione
from ammonizioni.motore.pesi import Pesi, attenua, carica_pesi, limita, salva_pesi
from ammonizioni.motore.tipi import decimale


def test_pesi_roundtrip_e_chiavi_mancanti(sessione):
    assert carica_pesi(sessione) == Pesi()  # niente salvato -> default

    pesi = Pesi(pesi_stagioni=(0.5, 0.3, 0.2), rivalita=1.5, soglie_diffida=(3, 8))
    salva_pesi(sessione, pesi)
    caricati = carica_pesi(sessione)
    assert caricati == pesi
    assert isinstance(caricati.pesi_stagioni, tuple)
    assert isinstance(caricati.soglie_diffida, tuple)
    assert isinstance(caricati.limiti_fattore, tuple)

    # chiavi mancanti -> default, chiavi sconosciute ignorate
    scrivi_impostazione(sessione, "pesi", {"rivalita": 1.4, "inesistente": 7})
    parziali = carica_pesi(sessione)
    assert parziali.rivalita == 1.4
    assert parziali.campo_caldo == Pesi().campo_caldo


def test_attenua_sotto_soglia():
    assert attenua(1.5, n=1, soglia=2, pesi=Pesi()) == pytest.approx(1.1)


def test_attenua_sopra_soglia_non_cambia():
    assert attenua(1.5, n=2, soglia=2, pesi=Pesi()) == pytest.approx(1.5)


def test_limita():
    assert limita(2.0, Pesi()) == 1.6
    assert limita(0.1, Pesi()) == 0.7
    assert limita(1.2, Pesi()) == 1.2


def test_decimale_con_virgola():
    assert decimale(5.4) == "5,4"
    assert decimale(5.0) == "5,0"
    assert decimale(0.25, 2) == "0,25"
