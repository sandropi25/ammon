"""Derby e campi caldi automatici: nomi risolti con gli alias, campo caldo dai cartellini,
unione con le righe manuali, Decimal di Postgres e guardia di regressione sulla classifica."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db_prova import CASA, PARTITA_FUTURA, TRASF, popola

from ammonizioni.db.modelli import Giocatore, ListaManuale, Partita, Presenza, Squadra
from ammonizioni.motore import rivalita
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.mercati import MercatoAmmonizioni

BASE = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
ADESSO = datetime(2026, 11, 5, 9, tzinfo=timezone.utc)


def _squadre(s, *nomi, primo_id=300):
    ids = {}
    for i, nome in enumerate(nomi):
        s.add(Squadra(id=primo_id + i, nome=nome))
        ids[nome] = primo_id + i
    s.flush()
    return ids


# ---------------------------------------------------------------- derby

def test_derby_predefinito_riconosciuto_anche_con_nomi_diversi_nel_db(sessione):
    ids = _squadre(
        sessione, "FC Internazionale Milano", "AC Milan", "AS Roma", "SS Lazio",
        "Atlético de Madrid", "FC Barcelona",
    )
    coppie = {d.coppia for d in rivalita.elenco_derby(sessione)}
    assert frozenset((ids["FC Internazionale Milano"], ids["AC Milan"])) in coppie
    assert frozenset((ids["AS Roma"], ids["SS Lazio"])) in coppie
    assert frozenset((ids["Atlético de Madrid"], ids["FC Barcelona"])) in coppie


def test_squadre_assenti_dal_db_ignorate_e_nessun_derby_senza_squadre(sessione):
    assert rivalita.elenco_derby(sessione) == []
    _squadre(sessione, "Sampdoria")  # il Genoa manca: la coppia Genoa-Sampdoria non esiste
    assert rivalita.derby_noti(sessione) == set()


def test_derby_manuale_resta_valido_in_unione_senza_doppioni(sessione):
    ids = _squadre(sessione, "Inter", "Milan", "Alfa", "Beta")
    sessione.add(ListaManuale(tipo="derby", squadra_a_id=ids["Milan"], squadra_b_id=ids["Inter"]))
    sessione.add(ListaManuale(tipo="derby", squadra_a_id=ids["Alfa"], squadra_b_id=ids["Beta"]))
    sessione.flush()
    derby = rivalita.elenco_derby(sessione)
    assert [d.origine for d in derby] == ["predefinito", "manuale"]  # Inter-Milan una volta sola
    assert rivalita.derby_noti(sessione) == {
        frozenset((ids["Inter"], ids["Milan"])), frozenset((ids["Alfa"], ids["Beta"])),
    }


def test_il_motore_usa_il_derby_predefinito(sessione):
    popola(sessione)
    sessione.query(ListaManuale).delete()  # nessuna riga manuale: basta l'elenco
    sessione.flush()
    assert not carica_dati(sessione, PARTITA_FUTURA).contesto.rivalita
    sessione.get(Squadra, CASA).nome = "FC Internazionale Milano"
    sessione.get(Squadra, TRASF).nome = "AC Milan"
    sessione.flush()
    assert carica_dati(sessione, PARTITA_FUTURA).contesto.rivalita


# ---------------------------------------------------------------- campo caldo

def _partite_in_casa(s, casa, n, cartellini, *, competizione=140, ospite=None, primo_pid=5000,
                     inizio=BASE):
    """`n` partite in casa di `casa` con `cartellini` gialli ciascuna (un solo giocatore)."""
    if s.get(Giocatore, 9000) is None:
        s.add(Giocatore(id=9000, nome="Giocatore di prova"))
        s.flush()
    ospite = ospite or (casa + 1000)
    if s.get(Squadra, ospite) is None:
        s.add(Squadra(id=ospite, nome=f"Ospite {ospite}"))
        s.flush()
    for i in range(n):
        pid = primo_pid + i
        s.add(Partita(id=pid, data_utc=inizio + timedelta(days=i), competizione_id=competizione,
                      stagione=2026, casa_id=casa, trasferta_id=ospite, stato="FT",
                      statistiche_scaricate=True))
        s.flush()
        s.add(Presenza(partita_id=pid, giocatore_id=9000, squadra_id=casa, gialli=cartellini))


def _lega(s):
    ids = _squadre(s, "Calda", "Fredda", primo_id=700)
    _partite_in_casa(s, ids["Calda"], 16, 6, primo_pid=5000)  # 6 cartellini a partita
    _partite_in_casa(s, ids["Fredda"], 16, 3, primo_pid=6000)  # 3: media del campionato 4,5
    return ids


def test_campo_caldo_sopra_il_venti_per_cento_con_il_motivo(sessione):
    ids = _lega(sessione)
    caldi = rivalita.campi_caldi_automatici(sessione, 2026, ADESSO)
    assert set(caldi) == {ids["Calda"]}
    c = caldi[ids["Calda"]]
    assert (c.partite, c.cartellini_casa, c.cartellini_lega) == (16, 6.0, 4.5)
    assert c.motivo == "Calda in casa: 6,0 cartellini a partita contro 4,5 di media"


def test_campo_caldo_servono_almeno_15_partite_in_casa(sessione):
    ids = _squadre(sessione, "Calda", "Fredda", primo_id=700)
    _partite_in_casa(sessione, ids["Calda"], 14, 6, primo_pid=5000)
    _partite_in_casa(sessione, ids["Fredda"], 16, 3, primo_pid=6000)
    assert rivalita.campi_caldi_automatici(sessione, 2026, ADESSO) == {}


def test_campo_caldo_sotto_la_soglia_del_venti_per_cento_no(sessione):
    ids = _squadre(sessione, "Quasi", "Fredda", primo_id=700)
    _partite_in_casa(sessione, ids["Quasi"], 16, 5, primo_pid=5000)
    _partite_in_casa(sessione, ids["Fredda"], 16, 3, primo_pid=6000)  # media (5+3)/2 = 4: 5 e' +25%
    assert set(rivalita.campi_caldi_automatici(sessione, 2026, ADESSO)) == {ids["Quasi"]}
    sessione.query(Presenza).filter(Presenza.partita_id >= 5000, Presenza.partita_id < 5016
                                    ).update({Presenza.gialli: 4})  # 4 contro 3,5: +14%
    sessione.flush()
    assert rivalita.campi_caldi_automatici(sessione, 2026, ADESSO) == {}


def test_campo_caldo_vede_solo_il_passato_e_solo_i_campionati(sessione):
    ids = _lega(sessione)
    prima_della_storia = BASE
    assert rivalita.campi_caldi_automatici(sessione, 2026, prima_della_storia) == {}
    # in Coppa (competizione 143) non e' campionato: non conta
    coppa = _squadre(sessione, "Coppa FC", primo_id=800)
    _partite_in_casa(sessione, coppa["Coppa FC"], 16, 9, competizione=143, primo_pid=7000)
    assert set(rivalita.campi_caldi_automatici(sessione, 2026, ADESSO)) == {ids["Calda"]}


def test_campo_caldo_manuale_in_unione_con_il_motivo(sessione):
    ids = _lega(sessione)
    manuale = _squadre(sessione, "Scelta a mano", primo_id=900)["Scelta a mano"]
    sessione.add(ListaManuale(tipo="campo_caldo", squadra_a_id=manuale))
    sessione.flush()
    assert rivalita.campi_caldi_noti(sessione, 2026, ADESSO) == {ids["Calda"], manuale}
    motivi = [c.motivo for c in rivalita.elenco_campi_caldi(sessione, 2026, ADESSO)]
    assert motivi == [
        "Calda in casa: 6,0 cartellini a partita contro 4,5 di media",
        "Scelta a mano: inserito a mano",
    ]


def test_campo_caldo_con_totali_decimal_di_postgres():
    """Su Postgres SUM() restituisce Decimal: medie e conteggi devono essere float/int."""
    class Risultato:
        def __init__(self, righe):
            self._righe = righe

        def all(self):
            return self._righe

    class SessioneDecimal:
        def __init__(self):
            self._risposte = [
                Risultato([
                    (140, 1, Decimal("16"), Decimal("96")),
                    (140, 2, Decimal("16"), Decimal("48")),
                ]),
                Risultato([(1, "Calda")]),
            ]

        def execute(self, _):
            return self._risposte.pop(0)

    caldi = rivalita.campi_caldi_automatici(SessioneDecimal(), 2026, ADESSO)
    c = caldi[1]
    assert isinstance(c.partite, int) and isinstance(c.cartellini_casa, float)
    assert isinstance(c.cartellini_lega, float)
    assert (c.cartellini_casa, c.cartellini_lega) == (6.0, 4.5)


# ---------------------------------------------------------------- guardia di regressione

def _classifica(s):
    return MercatoAmmonizioni().classifica(s, PARTITA_FUTURA, quote={12: 3.0})


def test_senza_partite_predefinite_la_classifica_e_quella_di_prima(sessione, monkeypatch):
    """Serie A: con squadre fuori dall'elenco e nessun campo caldo calcolabile (poche partite
    in casa) la classifica e' identica a quella con solo le liste manuali, come prima."""
    popola(sessione)
    sessione.add(ListaManuale(tipo="campo_caldo", squadra_a_id=CASA))  # le righe manuali valgono
    sessione.flush()
    con_automatici = _classifica(sessione)
    dati = carica_dati(sessione, PARTITA_FUTURA)
    assert dati.contesto.rivalita and dati.contesto.campo_caldo  # dal derby e campo manuali

    # "il vecchio motore": nessun derby predefinito e campo caldo automatico spento
    monkeypatch.setattr(rivalita, "DERBY_PREDEFINITI", {})
    monkeypatch.setattr(rivalita, "CAMPO_CALDO_PARTITE_MINIME", 10**9)
    vecchia = _classifica(sessione)
    assert con_automatici == vecchia
    assert carica_dati(sessione, PARTITA_FUTURA).contesto == dati.contesto


def test_la_classifica_cambia_solo_per_il_derby_riconosciuto(sessione, monkeypatch):
    popola(sessione)
    sessione.query(ListaManuale).delete()
    sessione.flush()
    senza = _classifica(sessione)
    assert not carica_dati(sessione, PARTITA_FUTURA).contesto.rivalita
    sessione.get(Squadra, CASA).nome = "FC Internazionale Milano"
    sessione.get(Squadra, TRASF).nome = "AC Milan"
    sessione.flush()
    con = _classifica(sessione)
    assert carica_dati(sessione, PARTITA_FUTURA).contesto.rivalita
    assert con != senza  # il derby alza le probabilita'
    assert {c.giocatore_id for c in con} == {c.giocatore_id for c in senza}
    # spenti i derby predefiniti, torna esattamente la classifica di prima
    monkeypatch.setattr(rivalita, "DERBY_PREDEFINITI", {})
    assert _classifica(sessione) == senza
