from datetime import datetime, timezone

import pytest
from costruttori import medie_standard, riga

from ammonizioni.motore.classifica import affidabilita, classifica, converti_quota
from ammonizioni.motore.fattori.base import MOTIVAZIONE_RITARDO
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import (
    ContestoInfo,
    DatiPartita,
    Fattore,
    MedieCampionato,
    MedieRuolo,
    StatArbitro,
    Titolare,
)

DATA = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def _contesto(**kw):
    valori = dict(rivalita=False, campo_caldo=False, posta={}, precedenti_n=0,
                  precedenti_gialli_medi=None)
    valori.update(kw)
    return ContestoInfo(**valori)


def _dati(storico=None, arbitro=None, contesto=None, medie=None, titolari=None):
    titolari = titolari if titolari is not None else [
        Titolare(10, "Mediano", 1, "M", "3:1", None),
        Titolare(11, "Portiere", 1, "G", "1:1", None),
        Titolare(20, "Rifinitore", 2, "M", "3:1", None),
    ]
    return DatiPartita(
        partita_id=100, data=DATA, stagione=2026, casa_id=1, trasferta_id=2,
        nomi_squadre={1: "Casa", 2: "Ospiti"}, titolari=titolari,
        storico=storico or {}, arbitro=arbitro, medie=medie or medie_standard(),
        contesto=contesto or _contesto(), duelli_manuali={},
    )


def _righe(n, **kw):
    return [riga(**kw) for _ in range(n)]


def test_probabilita_limitata_tra_2_e_70():
    # tantissimi gialli -> 0.70; medie con tasso minuscolo e nessun giallo -> 0.02
    alti = _dati(storico={10: _righe(40, gialli=3)}, arbitro=StatArbitro("R", 30, 9.0, 40.0, {}),
                 contesto=_contesto(rivalita=True, campo_caldo=True))
    assert next(c for c in classifica(alti, Pesi()) if c.giocatore_id == 10).probabilita == 0.70

    minime = MedieCampionato(4.2, 25.0, {
        r: MedieRuolo(0.0001, 1.3, 1.0, 1.0, 0.2, 6.0) for r in "GDMF"})
    bassi = _dati(storico={10: _righe(40, gialli=0, falli_commessi=0)}, medie=minime)
    assert next(c for c in classifica(bassi, Pesi()) if c.giocatore_id == 10).probabilita == 0.02


def _fattori(dati, giocatore_id=10):
    c = next(x for x in classifica(dati, Pesi()) if x.giocatore_id == giocatore_id)
    return {f.nome: f for f in c.fattori}


def test_storico_di_altro_campionato_non_cambia_base_e_situazione():
    """Un giocatore di Serie A con tanti gialli in Liga: base e situazione restano quelli
    calcolati solo con Serie A, Coppa Italia ed Europa (la Liga non e' il suo campionato)."""
    serie_a = _righe(10, gialli=0) + _righe(3, gialli=0, competizione_id=137)
    europa = _righe(3, gialli=0, competizione_id=2)
    liga = _righe(15, gialli=2, competizione_id=140, titolare=False) + _righe(
        5, gialli=1, competizione_id=143
    )
    senza = _fattori(_dati(storico={10: serie_a + europa}))
    con = _fattori(_dati(storico={10: serie_a + europa + liga}))
    assert con["base"].valore == senza["base"].valore
    assert con["base"].n_dati == senza["base"].n_dati
    assert con["situazione"].valore == senza["situazione"].valore
    assert con["situazione"].n_dati == senza["situazione"].n_dati


def test_storico_coppa_nazionale_e_europa_contano():
    """Coppa Italia ed Europa restano nella base di un giocatore di Serie A."""
    solo_campionato = _fattori(_dati(storico={10: _righe(10, gialli=0)}))
    con_coppe = _fattori(
        _dati(storico={10: _righe(10, gialli=0) + _righe(5, gialli=2, competizione_id=137)
                       + _righe(5, gialli=2, competizione_id=2)})
    )
    assert con_coppe["base"].valore > solo_campionato["base"].valore


def test_storia_mantiene_tutte_le_competizioni():
    """Il fattore storia (precedenti con l'avversario) resta trasversale ai campionati."""
    liga = [riga(competizione_id=140, avversario_id=2, gialli=1) for _ in range(4)]
    senza = _fattori(_dati(storico={10: _righe(10, gialli=0)}))
    con = _fattori(_dati(storico={10: _righe(10, gialli=0) + liga}))
    assert con["storia"].n_dati > senza["storia"].n_dati


def test_portieri_esclusi():
    ids = [c.giocatore_id for c in classifica(_dati(), Pesi())]
    assert 11 not in ids and {10, 20} <= set(ids)


def test_ordinata_per_probabilita_decrescente():
    dati = _dati(storico={10: _righe(10, gialli=1), 20: _righe(10, gialli=0)})
    c = classifica(dati, Pesi())
    assert [x.giocatore_id for x in c] == [10, 20]
    assert c[0].probabilita > c[1].probabilita


def test_fattori_nell_ordine():
    c = classifica(_dati(), Pesi())[0]
    assert [f.nome for f in c.fattori] == [
        "base", "duello", "arbitro", "contesto", "storia", "situazione"]


def test_motivazioni_al_massimo_3_le_piu_forti():
    # 4 giallo in Serie A (diffidato), tanti falli e pochi gialli (in ritardo),
    # arbitro severo, derby + campo caldo: 4 testi, restano i 3 piu' forti.
    storico = _righe(35, gialli=0, falli_commessi=3)
    storico[0] = riga(gialli=1, falli_commessi=3)
    storico[1] = riga(gialli=1, falli_commessi=3)
    storico[2] = riga(gialli=1, falli_commessi=3)
    storico[3] = riga(gialli=1, falli_commessi=3)
    dati = _dati(
        storico={10: storico},
        arbitro=StatArbitro("Rossi", 20, 5.4, 25.0, {}),
        contesto=_contesto(rivalita=True, campo_caldo=True),
    )
    cand = next(c for c in classifica(dati, Pesi()) if c.giocatore_id == 10)
    assert len(cand.motivazioni) == 3
    assert MOTIVAZIONE_RITARDO not in cand.motivazioni
    assert cand.motivazioni[0] == "Derby/rivalità · Campo caldo"
    assert cand.motivazioni[1] == "arbitro da 5,4 gialli"
    assert cand.motivazioni[2] == "Diffidato"


def test_motivazione_ritardo_se_unica():
    storico = _righe(10, gialli=0, falli_commessi=3)
    cand = next(c for c in classifica(_dati(storico={10: storico}), Pesi()) if c.giocatore_id == 10)
    assert cand.motivazioni == [MOTIVAZIONE_RITARDO]


def test_valore_con_quota():
    c = classifica(_dati(), Pesi(), quote={10: 4.0})
    cand = next(x for x in c if x.giocatore_id == 10)
    assert cand.quota == 4.0
    assert cand.prob_implicita == pytest.approx(0.25)
    assert cand.valore == pytest.approx(cand.probabilita - 0.25)
    altro = next(x for x in c if x.giocatore_id == 20)
    assert altro.quota is None and altro.prob_implicita is None and altro.valore is None


def test_avversario_diretto_usa_la_formazione_dei_compagni():
    # Due difensori di casa nella stessa riga: l'attaccante opposto marca lo specchio.
    titolari = [
        Titolare(1, "D sx", 1, "D", "2:1", None),
        Titolare(2, "D dx", 1, "D", "2:2", None),
        Titolare(3, "F sx", 2, "F", "4:1", None),
        Titolare(4, "F dx", 2, "F", "4:2", None),
    ]
    c = {x.giocatore_id: x for x in classifica(_dati(titolari=titolari), Pesi())}
    assert c[1].avversario_diretto_id == 4
    assert c[2].avversario_diretto_id == 3


def test_giocatore_senza_storico_in_classifica_con_dati_insufficienti():
    c = classifica(_dati(), Pesi())
    cand = next(x for x in c if x.giocatore_id == 10)
    assert cand.affidabilita == "dati insufficienti"
    assert 0.02 <= cand.probabilita <= 0.70


def _base(n_dati):
    return Fattore("base", 0.1, None, n_dati)


def test_affidabilita():
    arb = StatArbitro("R", 10, 4.0, 25.0, {})
    poco = StatArbitro("R", 2, 4.0, 25.0, {})
    p = Pesi()
    assert affidabilita(_base(269), arb, p) == "dati insufficienti"
    assert affidabilita(_base(270), arb, p) == "medio"
    assert affidabilita(_base(900), arb, p) == "alto"
    assert affidabilita(_base(900), poco, p) == "medio"
    assert affidabilita(_base(900), None, p) == "medio"


@pytest.mark.parametrize("t,atteso", [("2,10", 2.10), ("2.10", 2.10), (" 3 ", 3.0)])
def test_converti_quota_ok(t, atteso):
    assert converti_quota(t) == pytest.approx(atteso)


@pytest.mark.parametrize("t", ["1", "0", "-3", "abc", "", "1,0", "nan", "inf"])
def test_converti_quota_rifiutata(t):
    with pytest.raises(ValueError, match="Quota non valida: deve essere un numero maggiore di 1"):
        converti_quota(t)
