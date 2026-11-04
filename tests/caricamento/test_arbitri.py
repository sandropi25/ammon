import pytest
from sqlalchemy import select

from ammonizioni.caricamento.arbitri import normalizza, trova_o_crea
from ammonizioni.db.modelli import Arbitro


@pytest.mark.parametrize(
    "nome",
    [
        "D. Doveri",
        "Daniele Doveri",
        "Doveri D.",
        "DOVERI, Daniele",
        "Daniele Doveri, Italy",
        "D. Doveri, Italy",
    ],
)
def test_normalizza_arbitro(nome):
    assert normalizza(nome) == "doveri"


def test_normalizza_toglie_accenti_e_maiuscole():
    assert normalizza("José Sánchez, Spain") == "sanchez"


def test_normalizza_vuoto():
    assert normalizza("   ") == ""


def test_stesso_arbitro_una_riga(sessione):
    a = trova_o_crea(sessione, "D. Doveri")
    b = trova_o_crea(sessione, "Daniele Doveri, Italy")
    assert a.id == b.id
    assert len(sessione.scalars(select(Arbitro)).all()) == 1


def test_nome_visualizzato_senza_paese(sessione):
    a = trova_o_crea(sessione, "Daniele Doveri, Italy")
    assert a.nome_visualizzato == "Daniele Doveri"


@pytest.mark.parametrize("nome", [None, "", "  "])
def test_nome_vuoto_nessun_arbitro(sessione, nome):
    assert trova_o_crea(sessione, nome) is None
