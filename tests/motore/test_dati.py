from datetime import timedelta

import pytest
from costruttori import medie_standard
from db_prova import CASA, DATA_FUTURA, INIZIO, PARTITA_FUTURA, TRASF, popola
from sqlalchemy import update

from ammonizioni.db.modelli import (
    DuelloManuale,
    Formazione,
    Giocatore,
    ListaManuale,
    Partita,
    Presenza,
)
from ammonizioni.motore.dati import MEDIE_PREDEFINITE, carica_dati
from ammonizioni.motore.mercati import MercatoAmmonizioni
from ammonizioni.motore.tipi import RUOLI, Titolare


def test_carica_dati_base(sessione):
    popola(sessione)
    d = carica_dati(sessione, PARTITA_FUTURA)
    assert d.data == DATA_FUTURA and d.stagione == 2026
    assert (d.casa_id, d.trasferta_id) == (CASA, TRASF)
    assert d.nomi_squadre == {CASA: "Casa FC", TRASF: "Trasferta FC"}
    assert {t.giocatore_id for t in d.titolari} == {11, 12, 13, 14, 21, 22, 23, 24}
    t = next(t for t in d.titolari if t.giocatore_id == 12)
    assert (t.nome, t.squadra_id, t.ruolo, t.griglia) == ("Terzino Casa", CASA, "D", "2:1")
    assert all(len(d.storico[g]) == 6 for g in (12, 22))
    r = d.storico[12][0]
    assert r.avversario_id == TRASF and r.rivalita is True and r.competizione_id == 135


def test_contesto_arbitro_e_precedenti(sessione):
    popola(sessione)
    d = carica_dati(sessione, PARTITA_FUTURA)
    assert d.contesto.rivalita is True and d.contesto.campo_caldo is False
    assert d.contesto.precedenti_n == 5
    # 4 gialli (giocatori 12,14,22,24) nelle partite pari 2,4,6: ultime 5 = 2..6
    assert d.contesto.precedenti_gialli_medi == pytest.approx(12 / 5)
    assert d.arbitro.nome == "Rossi" and d.arbitro.partite == 6
    assert d.arbitro.gialli_medi == pytest.approx(4 * 3 / 6)
    assert d.arbitro.falli_medi == pytest.approx(16.0)
    assert d.arbitro.gialli_medi_con[CASA] == (pytest.approx(2.0), 6)
    assert d.medie.gialli_partita == pytest.approx(2.0)
    assert d.medie.falli_partita == pytest.approx(16.0)


def test_campo_caldo_solo_per_la_squadra_di_casa(sessione):
    popola(sessione)
    sessione.add(ListaManuale(tipo="campo_caldo", squadra_a_id=TRASF))
    sessione.flush()
    assert carica_dati(sessione, PARTITA_FUTURA).contesto.campo_caldo is False
    sessione.add(ListaManuale(tipo="campo_caldo", squadra_a_id=CASA))
    sessione.flush()
    assert carica_dati(sessione, PARTITA_FUTURA).contesto.campo_caldo is True


def test_senza_arbitro(sessione):
    popola(sessione, con_arbitro=False)
    assert carica_dati(sessione, PARTITA_FUTURA).arbitro is None


def test_medie_per_ruolo_e_predefinite(sessione):
    popola(sessione)
    m = carica_dati(sessione, PARTITA_FUTURA).medie
    # ruolo D: 2 giocatori x 6 partite x 90 min; gialli: 12 (pari) nelle 3 partite pari, 22 idem
    assert m.per_ruolo["D"].gialli90 == pytest.approx(6 / (12 * 90) * 90)
    assert m.per_ruolo["D"].falli90 == pytest.approx(2.0)
    assert m.per_ruolo["D"].voto == pytest.approx(6.0)
    # G: nessun giallo/dribbling/gol -> valori <= 0 sostituiti dai predefiniti
    assert m.per_ruolo["G"].gialli90 == MEDIE_PREDEFINITE.per_ruolo["G"].gialli90
    # lega senza alcun dribbling (come ESPN): dato assente = 0, non il valore predefinito
    assert m.per_ruolo["M"].dribbling90 == 0.0


def test_lega_senza_dribbling_e_senza_voti_segnala_dato_assente(sessione):
    popola(sessione)
    sessione.execute(update(Presenza).values(dribbling_tentati=0, voto=None))
    sessione.flush()
    m = carica_dati(sessione, PARTITA_FUTURA).medie
    for ruolo in RUOLI:
        assert m.per_ruolo[ruolo].dribbling90 == 0.0
        assert m.per_ruolo[ruolo].voto is None
    # le altre medie restano quelle misurate
    assert m.per_ruolo["D"].falli90 == pytest.approx(2.0)


def test_lega_con_dribbling_e_voti_usa_i_valori_misurati(sessione):
    """Guardia di regressione (dati tipo API-Football): nessun cambiamento rispetto a prima."""
    popola(sessione)
    sessione.execute(update(Presenza).where(Presenza.giocatore_id == 12).values(dribbling_tentati=3))
    sessione.flush()
    m = carica_dati(sessione, PARTITA_FUTURA).medie
    # ruolo D: giocatori 12 e 22 (6 partite x 90'), 3 dribbling x 6 partite -> 18 in 1080'
    assert m.per_ruolo["D"].dribbling90 == pytest.approx(18 / (12 * 90) * 90)
    assert m.per_ruolo["D"].voto == pytest.approx(6.0)
    # ruolo senza dribbling in una lega che li ha: ancora il predefinito, come prima
    assert m.per_ruolo["M"].dribbling90 == MEDIE_PREDEFINITE.per_ruolo["M"].dribbling90


def test_senza_dati_medie_predefinite(sessione):
    popola(sessione)
    d = carica_dati(sessione, PARTITA_FUTURA, prima_di=INIZIO)
    assert d.medie == MEDIE_PREDEFINITE
    # DB senza partite: ne' dribbling a 0 ne' voto assente, restano i predefiniti
    assert d.medie.per_ruolo["M"].dribbling90 == MEDIE_PREDEFINITE.per_ruolo["M"].dribbling90 > 0
    assert d.medie.per_ruolo["M"].voto == MEDIE_PREDEFINITE.per_ruolo["M"].voto
    assert d.arbitro is not None and d.arbitro.partite == 0
    assert d.contesto.precedenti_gialli_medi is None


def test_medie_predefinite_uguali_a_quelle_dei_test():
    assert MEDIE_PREDEFINITE == medie_standard()


def test_carica_dati_non_vede_partite_successive(sessione):
    popola(sessione)
    limite = INIZIO + timedelta(days=7 * 3)  # stessa istante della partita 3: esclusa
    d = carica_dati(sessione, PARTITA_FUTURA, prima_di=limite)
    assert {r.partita_id for r in d.storico[12]} == {1, 2}
    assert d.arbitro.partite == 2
    assert d.contesto.precedenti_n == 2
    # un'ora dopo la partita 3 la include
    d2 = carica_dati(sessione, PARTITA_FUTURA, prima_di=limite + timedelta(hours=1))
    assert {r.partita_id for r in d2.storico[12]} == {1, 2, 3}


def test_medie_non_vedono_partite_successive(sessione):
    popola(sessione)
    # il centrocampista 13 prende 3 gialli e fa 10 falli solo nella partita 5 (dopo il limite)
    p = sessione.get(Presenza, (5, 13))
    p.gialli, p.falli_commessi = 3, 10
    sessione.flush()
    limite = INIZIO + timedelta(days=7 * 3)  # partite 1 e 2 visibili
    m = carica_dati(sessione, PARTITA_FUTURA, prima_di=limite).medie
    assert m.gialli_partita == pytest.approx(2.0)
    assert m.falli_partita == pytest.approx(16.0)
    assert m.per_ruolo["M"].gialli90 == MEDIE_PREDEFINITE.per_ruolo["M"].gialli90
    assert m.per_ruolo["M"].falli90 == pytest.approx(2.0)
    # senza limite la partita 5 conta
    tutte = carica_dati(sessione, PARTITA_FUTURA).medie
    assert tutte.gialli_partita == pytest.approx((12 + 3) / 6)
    assert tutte.falli_partita == pytest.approx((16 * 6 + 8) / 6)
    assert tutte.per_ruolo["M"].gialli90 == pytest.approx(3 / (12 * 90) * 90)
    assert tutte.per_ruolo["M"].falli90 == pytest.approx((2 * 11 + 10) / 12)


def test_posta_non_vede_il_futuro(sessione):
    popola(sessione)
    # 19 vittorie casalinghe in Serie A (FT) tra le partite 6 e la futura
    for i in range(19):
        sessione.add(Partita(
            id=200 + i, data_utc=INIZIO + timedelta(days=43, hours=i), competizione_id=135,
            stagione=2026, casa_id=CASA, trasferta_id=TRASF, gol_casa=1, gol_trasferta=0,
            stato="FT"))
    sessione.flush()
    assert carica_dati(sessione, PARTITA_FUTURA).contesto.posta == {CASA: "titolo", TRASF: None}
    # con il limite prima di quelle partite la posta non cambia nulla
    d = carica_dati(sessione, PARTITA_FUTURA, prima_di=INIZIO + timedelta(days=43))
    assert d.contesto.posta == {CASA: None, TRASF: None}
    # 6 iniziali + 12 nuove = 18 giocate (< 19): nessuna posta; con una in piu' si arriva a 19
    d = carica_dati(sessione, PARTITA_FUTURA, prima_di=INIZIO + timedelta(days=43, hours=12))
    assert d.contesto.posta == {CASA: None, TRASF: None}
    d = carica_dati(sessione, PARTITA_FUTURA, prima_di=INIZIO + timedelta(days=43, hours=13))
    assert d.contesto.posta == {CASA: "titolo", TRASF: None}


def test_titolari_passati_hanno_la_precedenza(sessione):
    popola(sessione)
    mio = [Titolare(12, "X", CASA, "D", None, None), Titolare(22, "Y", TRASF, "D", None, None)]
    d = carica_dati(sessione, PARTITA_FUTURA, titolari=mio)
    assert d.titolari == mio
    assert set(d.storico) == {12, 22}


def test_formazione_probabile_se_manca_la_ufficiale(sessione):
    popola(sessione)
    for f in sessione.query(Formazione).all():
        f.tipo = "probabile"
    sessione.flush()
    assert len(carica_dati(sessione, PARTITA_FUTURA).titolari) == 8


def test_ultimo_xi_se_nessuna_formazione(sessione):
    popola(sessione, con_formazione=False)
    sessione.get(Presenza, (6, 14)).titolare = False  # in panchina nell'ultima
    sessione.flush()
    d = carica_dati(sessione, PARTITA_FUTURA)
    assert {t.giocatore_id for t in d.titolari} == {11, 12, 13, 21, 22, 23, 24}


def test_ultimo_xi_rispetta_prima_di(sessione):
    popola(sessione, con_formazione=False)
    sessione.get(Presenza, (6, 14)).titolare = False  # fuori nell'ultima
    sessione.get(Presenza, (2, 13)).titolare = False  # fuori nella seconda
    sessione.flush()
    tutti = {t.giocatore_id for t in carica_dati(sessione, PARTITA_FUTURA).titolari}
    assert 14 not in tutti and 13 in tutti
    # limite alla partita 3 (esclusa): l'ultimo XI e' quello della partita 2
    prima = {
        t.giocatore_id
        for t in carica_dati(
            sessione, PARTITA_FUTURA, prima_di=INIZIO + timedelta(days=7 * 3)
        ).titolari
    }
    assert 13 not in prima and 14 in prima
    # limite alla partita 1: nessuna partita precedente, nessun XI
    assert carica_dati(sessione, PARTITA_FUTURA, prima_di=INIZIO + timedelta(days=7)).titolari == []


def test_ruolo_sconosciuto_diventa_M(sessione):
    popola(sessione)
    sessione.get(Giocatore, 14).ruolo = None
    sessione.flush()
    t = next(t for t in carica_dati(sessione, PARTITA_FUTURA).titolari if t.giocatore_id == 14)
    assert t.ruolo == "M"


def test_duelli_manuali(sessione):
    popola(sessione)
    sessione.add(DuelloManuale(partita_id=PARTITA_FUTURA, giocatore_id=12, avversario_id=24))
    sessione.flush()
    assert carica_dati(sessione, PARTITA_FUTURA).duelli_manuali == {12: 24}


def test_storico_include_altre_competizioni_e_stagioni_ma_non_vecchie(sessione):
    popola(sessione)
    for pid, comp, stag in ((50, 2, 2026), (51, 135, 2025), (52, 135, 2023)):
        sessione.add(Partita(
            id=pid, data_utc=INIZIO - timedelta(days=30 * (pid - 49)), competizione_id=comp,
            stagione=stag, casa_id=CASA, trasferta_id=TRASF, stato="FT",
            statistiche_scaricate=True))
        sessione.flush()
        sessione.add(Presenza(partita_id=pid, giocatore_id=12, squadra_id=CASA, titolare=True,
                              ruolo="D", minuti=90))
    sessione.flush()
    ids = {r.partita_id for r in carica_dati(sessione, PARTITA_FUTURA).storico[12]}
    assert {50, 51} <= ids and 52 not in ids


def test_mercato_ammonizioni_end_to_end(sessione):
    popola(sessione)
    mercato = MercatoAmmonizioni()
    assert mercato.nome == "ammonizioni"
    c = mercato.classifica(sessione, PARTITA_FUTURA, quote={12: 3.0})
    assert {x.giocatore_id for x in c} == {12, 13, 14, 22, 23, 24}  # senza portieri
    probs = [x.probabilita for x in c]
    assert probs == sorted(probs, reverse=True)
    assert all(0.02 <= p <= 0.70 for p in probs)
    top = c[0]
    assert top.giocatore_id in (12, 14, 22, 24)  # quelli che prendono gialli
    assert all(x.avversario_diretto_id is not None for x in c)
    cand = next(x for x in c if x.giocatore_id == 12)
    assert cand.valore == pytest.approx(cand.probabilita - 1 / 3.0)
    assert cand.affidabilita == "medio"  # 540 minuti (< 900), arbitro con 6 partite


def test_mercato_ammonizioni_senza_arbitro(sessione):
    popola(sessione, con_arbitro=False)
    c = MercatoAmmonizioni().classifica(sessione, PARTITA_FUTURA)
    assert len(c) == 6
    for x in c:
        arbitro = next(f for f in x.fattori if f.nome == "arbitro")
        assert arbitro.valore == 1.0 and arbitro.motivazione is None
        assert x.affidabilita == "medio"


def test_gialli_dalla_panchina_contano_nella_media_di_ruolo(sessione):
    """Un giallo preso da chi non e' mai entrato (minuti 0) conta nei gialli/90 della lega,
    come conta nel tasso del giocatore; i minuti sommati restano solo quelli giocati."""
    popola(sessione)
    sessione.add(Giocatore(id=15, nome="Panchinaro Casa", ruolo="D"))
    sessione.flush()
    sessione.add(
        Presenza(
            partita_id=1, giocatore_id=15, squadra_id=CASA, titolare=False, ruolo="D",
            minuti=0, gialli=1,
        )
    )
    sessione.flush()
    m = carica_dati(sessione, PARTITA_FUTURA).medie
    assert m.per_ruolo["D"].gialli90 == pytest.approx(7 / (12 * 90) * 90)
    assert m.per_ruolo["D"].falli90 == pytest.approx(2.0)
