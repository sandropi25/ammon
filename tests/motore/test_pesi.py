import logging
from dataclasses import replace

import pytest

from ammonizioni.db.repo import scrivi_impostazione
from ammonizioni.motore.pesi import (
    Pesi,
    attenua,
    carica_pesi,
    limita,
    salva_pesi,
    valida_pesi,
)
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


PESI_NON_VALIDI = [
    ("minuti_prior", 0),
    ("bonus_ritardo", 0),
    ("rivalita", 0),
    ("campo_caldo", 0),
    ("posta", 0),
    ("diffidato", 0),
    ("sostituzione", -0.5),
    ("pesi_stagioni", (0.0, 0.0, 0.0)),
    ("pesi_stagioni", (-0.1, 0.6, 0.5)),
    ("pesi_stagioni", (0.6, 0.4)),
    ("limiti_fattore", (0.0, 1.6)),
    ("limiti_fattore", (1.6, 0.7)),
    ("limiti_probabilita", (0.0, 0.7)),
    ("limiti_probabilita", (0.02, 1.0)),
    ("soglia_partite_arbitro", 0),
    ("soglia_precedenti", 0),
]


@pytest.mark.parametrize("campo, valore", PESI_NON_VALIDI)
def test_valida_pesi_rifiuta_i_valori_che_bloccano_il_motore(campo, valore):
    with pytest.raises(ValueError, match=campo):
        valida_pesi(replace(Pesi(), **{campo: valore}))


def test_valida_pesi_accetta_i_default_e_coefficienti_nulli():
    valida_pesi(Pesi())
    valida_pesi(Pesi(coeff_forma=0, coeff_storia=0, pesi_stagioni=(1.0, 0.0, 0.0)))


@pytest.mark.parametrize("campo, valore", PESI_NON_VALIDI + [("minuti_prior", "abc")])
def test_carica_pesi_non_validi_nel_db_torna_ai_default(sessione, caplog, campo, valore):
    scrivi_impostazione(
        sessione, "pesi", {campo: list(valore) if isinstance(valore, tuple) else valore}
    )
    with caplog.at_level(logging.WARNING, logger="ammonizioni.motore.pesi"):
        assert carica_pesi(sessione) == Pesi()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


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
