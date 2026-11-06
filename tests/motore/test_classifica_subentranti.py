from datetime import datetime, timezone

import pytest
from costruttori import medie_standard, riga

from ammonizioni.motore.classifica import classifica, classifica_subentranti
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import ContestoInfo, DatiPartita, Titolare

DATA = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)
TITOLARI = [
    Titolare(1, "Punta fissa", 1, "F", "4:1", None),
    Titolare(2, "Punta che esce", 1, "F", "4:2", None),
    Titolare(3, "Difensore fisso", 1, "D", "2:1", None),
    Titolare(4, "Mediano ospite", 2, "M", "3:1", None),
]
STORICO_TITOLARI = {
    1: [riga(minuti=90)] * 6,
    2: [riga(minuti=65)] * 6,
    3: [riga(minuti=90)] * 6,
    4: [riga(minuti=90)] * 6,
}


def _panchine(entra, totale, minuti=25, **kw):
    return [riga(titolare=False, minuti=minuti if i < entra else 0, **kw) for i in range(totale)]


def _dati(panchina, storico, prob=None, tendenza=None):
    return DatiPartita(
        partita_id=100, data=DATA, stagione=2026, casa_id=1, trasferta_id=2,
        nomi_squadre={1: "Casa", 2: "Ospiti"}, titolari=TITOLARI,
        storico={**STORICO_TITOLARI, **storico}, arbitro=None, medie=medie_standard(),
        contesto=ContestoInfo(False, False, {}, 0, None), duelli_manuali={},
        panchina=panchina, prob_vittoria=prob or {}, tendenza_cambi=tendenza or {},
    )


def test_subentrante_che_entra_spesso_collegato_al_titolare_piu_sostituito():
    b = Titolare(10, "Punta di riserva", 1, "F", None, None)
    (c,) = classifica_subentranti(_dati([b], {10: _panchine(8, 10)}), Pesi())
    assert c.subentrante and c.avversario_diretto_id is None
    assert c.subentro.al_posto_di_id == 2 and c.subentro.al_posto_di_nome == "Punta che esce"
    assert c.subentro.probabilita_ingresso > 0.6
    assert c.subentro.minuti_medi == pytest.approx(25)
    assert 0.02 <= c.probabilita <= 0.70
    assert [f.nome for f in c.fattori] == [
        "base", "ingresso", "arbitro", "contesto", "storia", "situazione"]


def test_probabilita_formula():
    b = Titolare(10, "Riserva", 1, "F", None, None)
    (c,) = classifica_subentranti(_dati([b], {10: _panchine(8, 10)}), Pesi())
    f = {x.nome: x.valore for x in c.fattori}
    atteso = f["ingresso"] * f["base"] * f["arbitro"] * f["contesto"] * f["storia"] * f["situazione"]
    assert c.probabilita == pytest.approx(max(0.02, atteso))


def test_sotto_la_media_compare_comunque_senza_evidenza():
    tranquillo = _panchine(10, 10, minuti=30, falli_commessi=0, gialli=0)
    b = Titolare(10, "Riserva tranquilla", 1, "F", None, None)
    (c,) = classifica_subentranti(_dati([b], {10: tranquillo}), Pesi())
    assert c.subentro.sopra_media is False
    assert c.subentro.gialli90 == 0.0 and c.subentro.falli90 == 0.0


def test_sopra_la_media_compare_con_evidenza():
    nervoso = _panchine(10, 10, minuti=30, falli_commessi=2, gialli=0)
    b = Titolare(10, "Riserva nervosa", 1, "F", None, None)
    (c,) = classifica_subentranti(_dati([b], {10: nervoso}), Pesi())
    assert c.subentro.sopra_media is True
    assert c.subentro.falli90 == pytest.approx(6.0)
    assert c.subentro.media_falli90 == medie_standard().per_ruolo["F"].falli90


def test_nessun_titolare_dello_stesso_ruolo_sostituito_senza_nome():
    b = Titolare(10, "Difensore di riserva", 1, "D", None, None)
    (c,) = classifica_subentranti(_dati([b], {10: _panchine(8, 10)}), Pesi())
    assert c.subentro.al_posto_di_id is None and c.subentro.al_posto_di_nome is None


def test_chi_entra_poco_non_compare_e_portieri_esclusi():
    terzo_portiere = Titolare(10, "Terzo portiere", 1, "G", None, None)
    mai = Titolare(11, "Mai in campo", 1, "D", None, None)
    nuovo = Titolare(12, "Senza panchine", 1, "M", None, None)
    dati = _dati(
        [terzo_portiere, mai, nuovo],
        {10: _panchine(0, 15), 11: _panchine(0, 15), 12: [riga(minuti=90)]},
    )
    assert classifica_subentranti(dati, Pesi()) == []


def test_mai_entrato_in_poche_panchine_non_compare():
    """Con 6 panchine e nessun ingresso il restringimento darebbe ~0,2: resta fuori."""
    mai = Titolare(11, "Mai in campo", 1, "F", None, None)
    assert classifica_subentranti(_dati([mai], {11: _panchine(0, 6)}), Pesi()) == []
    # con 3 panchine senza ingressi il dato è troppo scarso per escluderlo
    assert len(classifica_subentranti(_dati([mai], {11: _panchine(0, 3)}), Pesi())) == 1


def test_ordinati_per_probabilita():
    spesso = Titolare(10, "Spesso", 1, "F", None, None)
    raro = Titolare(11, "Raro", 2, "M", None, None)
    dati = _dati([raro, spesso], {10: _panchine(9, 10, minuti=40), 11: _panchine(2, 10, minuti=10)})
    ids = [c.giocatore_id for c in classifica_subentranti(dati, Pesi())]
    assert ids == [10, 11]


def test_sfavorita_alza_gli_attaccanti():
    b = Titolare(10, "Punta", 1, "F", None, None)
    storico = {10: _panchine(5, 10) + _panchine(3, 3, minuti=30, gialli=1)}
    tendenza = {1: {"F": 0.4, "M": 0.3, "D": 0.3}}
    pari = classifica_subentranti(_dati([b], storico, tendenza=tendenza), Pesi())[0]
    sotto = classifica_subentranti(
        _dati([b], storico, prob={1: 0.2, 2: 0.55}, tendenza=tendenza), Pesi()
    )[0]
    assert sotto.subentro.sfavorita and not pari.subentro.sfavorita
    assert sotto.subentro.probabilita_ingresso > pari.subentro.probabilita_ingresso
    assert sotto.probabilita > pari.probabilita


def test_giallo_dalla_panchina_conta():
    b = Titolare(10, "Riserva", 1, "M", None, None)
    senza = _panchine(6, 10, minuti=30)
    con = senza + [riga(titolare=False, minuti=0, gialli=1)]
    p_senza = classifica_subentranti(_dati([b], {10: senza}), Pesi())[0]
    p_con = classifica_subentranti(_dati([b], {10: con}), Pesi())[0]
    assert p_con.subentro.gialli90 > p_senza.subentro.gialli90
    assert p_con.probabilita > p_senza.probabilita


def test_panchina_non_cambia_i_titolari():
    b = Titolare(10, "Riserva", 1, "F", None, None)
    senza = classifica(_dati([], {}), Pesi())
    con = classifica(_dati([b], {10: _panchine(8, 10)}, prob={1: 0.2, 2: 0.6}), Pesi())
    assert [(c.giocatore_id, c.probabilita) for c in con] == [
        (c.giocatore_id, c.probabilita) for c in senza
    ]
    assert not any(c.subentrante for c in con)


def test_senza_panchina_nessun_subentrante():
    assert classifica_subentranti(_dati([], {}), Pesi()) == []
