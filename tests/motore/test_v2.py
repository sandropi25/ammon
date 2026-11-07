import math

import numpy as np
import pytest
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola, popola_panchina

from ammonizioni.motore import modello, v2
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.pesi import Pesi

COEFF = v2.CoefficientiV2(
    partita={"intercetta": 0.1, "arbitro": 0.5, "derby": 0.1},
    giocatore={"tasso": 0.8, "falli": 0.3, "ruolo_D": 0.5, "ruolo_M": 0.5, "ruolo_F": 0.2,
               "subentrante": 0.3},
)


def _dati(s):
    popola(s)
    popola_panchina(s)
    return carica_dati(s, PARTITA_FUTURA, con_panchina=True)


def test_le_attese_dei_giocatori_sommano_a_lambda(sessione):
    dati = _dati(sessione)
    prev = v2.previsione(dati, Pesi(), COEFF)
    assert sum(prev.quote.values()) == pytest.approx(1.0)
    attese = sum(-math.log(1 - p) for p in prev.probabilita.values())
    assert attese == pytest.approx(prev.lambda_partita)
    # titolari e panchina (portieri compresi) sono tutti nella distinta
    assert set(prev.probabilita) == {11, 12, 13, 14, 21, 22, 23, 24, 15, 16, 17, 25}


def test_lambda_parte_dalla_media_del_campionato(sessione):
    dati = _dati(sessione)
    x, offset = v2.caratteristiche_partita(dati)
    assert offset == pytest.approx(math.log(dati.medie.gialli_partita))
    assert x[v2.NOMI_PARTITA.index("derby")] == 1.0
    neutro = v2.previsione(dati, Pesi(), v2.COEFFICIENTI_NEUTRI)
    assert neutro.lambda_partita == pytest.approx(dati.medie.gialli_partita)


def test_arbitro_ristretto_verso_la_media(sessione):
    dati = _dati(sessione)
    x, _ = v2.caratteristiche_partita(dati)
    a = dati.arbitro
    media = dati.medie.gialli_partita
    atteso = (a.gialli_medi * a.partite + v2.PRIOR_ARBITRO * media) / (a.partite + v2.PRIOR_ARBITRO)
    assert x[v2.NOMI_PARTITA.index("arbitro")] == pytest.approx(math.log(atteso / media))


def test_chi_prende_piu_gialli_ha_quota_piu_alta(sessione):
    dati = _dati(sessione)
    prev = v2.previsione(dati, Pesi(), COEFF)
    # 12 e 14 hanno gialli nelle partite pari, 13 nessuno (stesso minutaggio)
    assert prev.probabilita[12] > prev.probabilita[13]


def test_panchinaro_che_non_entra_quasi_mai_conta_poco(sessione):
    dati = _dati(sessione)
    g = v2.caratteristiche_giocatori(dati, Pesi())
    minuti = dict(zip(g.ids, np.exp(g.log_minuti) * 90))
    assert minuti[17] < minuti[15] < minuti[12]
    assert minuti[17] >= v2.MINUTI_PANCHINA  # può comunque prendere un giallo in panchina


def test_coefficienti_json_andata_e_ritorno():
    c = v2.CoefficientiV2({"intercetta": 0.2}, {"tasso": 0.9}, "2026-11-07", {"partite": 10})
    assert v2.CoefficientiV2.da_json(c.come_json()) == c
    assert v2.CoefficientiV2.da_json({"partita": {"intercetta": "x"}, "giocatore": {}}) is None
    assert v2.CoefficientiV2.da_json({"partita": {"intercetta": float("nan")},
                                      "giocatore": {}}) is None
    assert v2.CoefficientiV2.da_json("rotto") is None


def test_modello_predefinito_v1_e_scelta_salvata(sessione):
    assert modello.modello_scelto(sessione) == "V1"
    modello.salva_modello(sessione, "V2")
    assert modello.modello_scelto(sessione) == "V2"
    with pytest.raises(ValueError):
        modello.salva_modello(sessione, "V3")


def test_coefficienti_salvati_o_predefiniti(sessione):
    assert modello.carica_coefficienti(sessione) == v2.COEFFICIENTI_PREDEFINITI
    modello.salva_coefficienti(sessione, COEFF)
    assert modello.carica_coefficienti(sessione) == COEFF


def test_v2_da_probabilita_a_titolari_e_subentranti(sessione):
    dati = _dati(sessione)
    t1, b1 = modello.candidati(dati, Pesi(), modello="V1")
    t2, b2 = modello.candidati(dati, Pesi(), modello="V2", coeff=COEFF)
    prev = v2.previsione(dati, Pesi(), COEFF)
    assert {c.giocatore_id for c in t2} == {c.giocatore_id for c in t1}
    assert {c.giocatore_id for c in b2} == {c.giocatore_id for c in b1} and b2
    for c in t2 + b2:
        assert c.probabilita == pytest.approx(prev.probabilita[c.giocatore_id])
        assert c.fattori[-2].nome == "partita" and c.fattori[-1].nome == "quota"
    # stessa affidabilità e motivazioni di V1
    per_id = {c.giocatore_id: c for c in t1 + b1}
    for c in t2 + b2:
        assert c.affidabilita_punti == per_id[c.giocatore_id].affidabilita_punti
        assert c.motivazioni == per_id[c.giocatore_id].motivazioni
    assert [c.probabilita for c in t2] == sorted((c.probabilita for c in t2), reverse=True)


def test_v2_con_quote_ricalcola_il_valore(sessione):
    dati = _dati(sessione)
    t2, _ = modello.candidati(dati, Pesi(), {12: 4.0}, modello="V2", coeff=COEFF)
    c = next(c for c in t2 if c.giocatore_id == 12)
    assert c.valore == pytest.approx(c.probabilita - 0.25)


def test_squadre_entrano_nelle_caratteristiche(sessione):
    dati = _dati(sessione)
    assert set(dati.stat_squadre) == {CASA, TRASF}
    g = v2.caratteristiche_giocatori(dati, Pesi())
    i = g.ids.index(12)
    assert g.Z[i, v2.NOMI_GIOCATORE.index("casa")] == 1.0
    assert g.Z[g.ids.index(22), v2.NOMI_GIOCATORE.index("casa")] == 0.0
    assert g.Z[g.ids.index(15), v2.NOMI_GIOCATORE.index("subentrante")] == 1.0
