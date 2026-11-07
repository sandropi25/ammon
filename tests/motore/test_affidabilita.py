from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from costruttori import medie_standard, riga
from db_prova import PARTITA_FUTURA, popola

from ammonizioni.motore import affidabilita as aff
from ammonizioni.motore.classifica import classifica, classifica_subentranti
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.mercati import MercatoAmmonizioni
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import (
    ContestoInfo,
    DatiPartita,
    InfoSubentro,
    StatArbitro,
    Titolare,
)

DATA = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def _righe_complete(n=30, **kw):
    """n partite da 90' in 3 stagioni, ogni 36 giorni a ritroso (le ultime 2 recenti)."""
    return [
        riga(
            partita_id=1000 + i,
            data=DATA - timedelta(days=10 + 36 * i),
            stagione=2026 - (i // 10),
            **kw,
        )
        for i in range(n)
    ]


def _calcola(storico, **kw):
    valori = dict(
        storico=storico, data=DATA, arbitro=StatArbitro("Doveri", 24, 4.0, 25.0, {}),
        formazione_ufficiale=True, avversario_squadra_id=2, nome_avversario="Udinese",
        derby=False, avversario_diretto=aff.CERTO,
    )
    valori.update(kw)
    return aff.calcola(**valori)


def test_livelli_alle_soglie():
    assert [aff.livello(p) for p in (100, 70, 69, 40, 39, 0)] == [
        "alta", "alta", "media", "media", "bassa", "bassa"
    ]
    assert [aff.vecchia_etichetta(p) for p in (70, 69, 40, 39)] == [
        "alto", "medio", "medio", "dati insufficienti"
    ]


def test_dati_pieni_punteggio_alto_e_motivi_in_chiaro():
    storico = _righe_complete(30, gialli=0)
    for r in range(0, 30, 4):  # gialli in 8 partite diverse
        storico[r] = replace(storico[r], gialli=1)
    storico = [replace(r, avversario_id=2) if i % 7 == 0 else replace(r, avversario_id=9)
               for i, r in enumerate(storico)]
    a = _calcola(storico)
    assert a.punti >= 90 and a.livello == "alta"
    testo = " | ".join(a.motivi)
    assert "2.700 minuti in 3 stagioni" in testo
    assert "formazione ufficiale" in testo
    assert "arbitro designato (24 partite)" in testo
    assert "avversario diretto certo" in testo
    assert "5 precedenti contro Udinese" in testo
    assert "gialli in 8 partite diverse" in testo


def test_senza_nulla_punteggio_basso_e_i_motivi_dicono_cosa_manca():
    a = _calcola(
        [], arbitro=None, formazione_ufficiale=False, avversario_diretto=aff.INCERTO
    )
    assert a.punti == 5 and a.livello == "bassa"  # solo la formazione probabile
    testo = " | ".join(a.motivi)
    for atteso in (
        "nessun minuto nei dati", "formazione solo probabile", "arbitro non ancora designato",
        "avversario diretto incerto", "nessun precedente contro Udinese",
        "nessuna presenza negli ultimi 60 giorni", "nessun giallo nei dati",
    ):
        assert atteso in testo


@pytest.mark.parametrize(
    "variazione",
    [
        dict(formazione_ufficiale=False),
        dict(arbitro=None),
        dict(avversario_diretto=aff.INCERTO),
        dict(avversario_diretto=aff.PROBABILE),
        dict(arbitro=StatArbitro("Doveri", 3, 4.0, 25.0, {})),
    ],
)
def test_ogni_fattore_che_manca_abbassa_il_punteggio(variazione):
    storico = _righe_complete(30, gialli=0)
    assert _calcola(storico, **variazione).punti < _calcola(storico).punti


def test_piu_minuti_piu_punti_ma_mai_oltre_100():
    poche = _calcola(_righe_complete(5)).punti
    molte = _calcola(_righe_complete(30)).punti
    moltissime = _calcola(_righe_complete(60)).punti
    assert poche < molte <= moltissime <= 100


def test_attivita_recente_e_derby():
    fermo = _righe_complete(10)
    recente = [replace(r, data=DATA - timedelta(days=5 + i)) for i, r in enumerate(fermo)]
    assert _calcola(recente).punti > _calcola(fermo).punti
    assert any("negli ultimi 60 giorni" in m for m in _calcola(recente).motivi)
    storico = [replace(r, avversario_id=2) for r in fermo[:3]]
    assert any("(derby)" in m for m in _calcola(storico, derby=True).motivi)
    assert not any("(derby)" in m for m in _calcola(storico).motivi)


def test_un_giallo_dalla_panchina_senza_minuti_conta():
    storico = [riga(partita_id=1, data=DATA - timedelta(days=3), minuti=0, gialli=1,
                    titolare=False, avversario_id=2)]
    motivi = " | ".join(_calcola(storico).motivi)
    assert "gialli in 1 partita" in motivi
    assert "1 precedente contro Udinese" in motivi
    assert "1 partita negli ultimi 60 giorni" in motivi


def test_subentrante_conta_panchine_e_tendenza_dei_cambi():
    info = InfoSubentro(0.5, 20.0, 12, 6, None, None, 0.3, 1.0, 0.2, 1.3, False, False)
    storico = [riga(minuti=20, titolare=False, avversario_id=2) for _ in range(6)]
    con = _calcola(storico, subentro=info, tendenza_nota=True, avversario_diretto=aff.INCERTO)
    senza = _calcola(storico, subentro=info, tendenza_nota=False, avversario_diretto=aff.INCERTO)
    assert con.punti == senza.punti + 10
    testo = " | ".join(con.motivi)
    assert "12 panchine recenti, 6 ingressi" in testo
    assert "tendenza dei cambi della squadra nota" in testo
    assert "avversario diretto" not in testo
    sola_una = replace(info, panchine=1, ingressi=1)
    assert "1 panchina recenti, 1 ingresso" in " | ".join(_calcola(storico, subentro=sola_una).motivi)


# --- nella classifica ----------------------------------------------------------


def _dati(storico, ufficiali=True, arbitro=None, duelli=None):
    return DatiPartita(
        partita_id=100, data=DATA, stagione=2026, casa_id=1, trasferta_id=2,
        nomi_squadre={1: "Casa", 2: "Ospiti"},
        titolari=[
            Titolare(10, "Mediano", 1, "M", "3:1", None),
            Titolare(20, "Rifinitore", 2, "M", "3:1", None),
        ],
        storico=storico, arbitro=arbitro, medie=medie_standard(),
        contesto=ContestoInfo(False, False, {}, 0, None), duelli_manuali=duelli or {},
        formazioni_ufficiali=ufficiali,
    )


def test_la_classifica_porta_punteggio_e_motivi_e_deriva_il_vecchio_campo():
    storico = {10: _righe_complete(30), 20: []}
    c = {x.giocatore_id: x for x in classifica(_dati(storico), Pesi())}
    assert c[10].affidabilita_punti > c[20].affidabilita_punti
    assert c[10].affidabilita == aff.vecchia_etichetta(c[10].affidabilita_punti)
    assert c[20].affidabilita == "dati insufficienti"
    assert any("formazione ufficiale" in m for m in c[10].affidabilita_motivi)
    assert any("avversario diretto certo" in m for m in c[10].affidabilita_motivi)
    probabile = {x.giocatore_id: x for x in classifica(_dati(storico, ufficiali=False), Pesi())}
    assert any("avversario diretto probabile" in m for m in probabile[10].affidabilita_motivi)
    assert probabile[10].affidabilita_punti < c[10].affidabilita_punti


def test_duello_manuale_rende_certo_l_avversario_anche_con_formazione_probabile():
    storico = {10: _righe_complete(30), 20: _righe_complete(3)}
    c = {x.giocatore_id: x for x in classifica(_dati(storico, ufficiali=False, duelli={10: 20}), Pesi())}
    assert any("avversario diretto certo" in m for m in c[10].affidabilita_motivi)


# --- la probabilità NON cambia -------------------------------------------------


def test_probabilita_e_ordine_dei_titolari_identici_a_prima(sessione):
    """Valori di riferimento calcolati col codice precedente all'affidabilità precisa (V1)."""
    from ammonizioni.motore import modello

    popola(sessione)
    modello.salva_modello(sessione, "V1")
    c = MercatoAmmonizioni().classifica(sessione, PARTITA_FUTURA)
    assert [(x.giocatore_id, x.probabilita) for x in c] == [
        (12, 0.49844576734446583), (14, 0.49844576734446583), (22, 0.49844576734446583),
        (24, 0.49844576734446583), (13, 0.11438581476253065), (23, 0.11438581476253065),
    ]


def test_probabilita_indipendente_da_tutto_cio_che_riguarda_solo_l_affidabilita():
    storico = {10: _righe_complete(30, gialli=1), 20: _righe_complete(4)}
    base = classifica(_dati(storico, ufficiali=False), Pesi())
    altro = classifica(_dati(storico, ufficiali=True), Pesi())
    assert [(x.giocatore_id, x.probabilita) for x in base] == [
        (x.giocatore_id, x.probabilita) for x in altro
    ]
    assert [x.affidabilita_punti for x in base] != [x.affidabilita_punti for x in altro]


def test_subentranti_stessa_probabilita_con_formazioni_ufficiali_o_probabili():
    storico = {
        10: _righe_complete(10), 20: _righe_complete(10),
        30: [riga(minuti=25, titolare=False, gialli=i % 2) for i in range(10)],
    }
    prob = {}
    for ufficiali in (False, True):
        d = replace(_dati(storico, ufficiali=ufficiali), panchina=[Titolare(30, "Panchinaro", 1, "F", None, None)],
                    tendenza_cambi={1: {"F": 1.0}})
        sub = classifica_subentranti(d, Pesi())
        assert [x.giocatore_id for x in sub] == [30]
        prob[ufficiali] = (sub[0].probabilita, sub[0].affidabilita_punti)
    assert prob[False][0] == prob[True][0]
    assert prob[False][1] < prob[True][1]


def test_carica_dati_segna_se_le_formazioni_sono_ufficiali(sessione):
    popola(sessione)
    dati = carica_dati(sessione, PARTITA_FUTURA)
    from ammonizioni.db.modelli import Partita

    ufficiali = sessione.get(Partita, PARTITA_FUTURA).stato_formazioni == "ufficiali"
    assert dati.formazioni_ufficiali is ufficiali
