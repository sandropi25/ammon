"""Partite calde: calore (cartellini attesi e motivi), calcolo raggruppato dal DB, pagina."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import componenti
import componenti_calde
import pytest
from ayuda_app import PAGINA_CALDE, avvia, sessione_db, url_db, visibile  # noqa: F401
from sqlalchemy import event

from ammonizioni.db.modelli import Arbitro, Giocatore, ListaManuale, Partita, Presenza, Squadra

ORA = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- calore (logica pura)

def test_precedenti_molto_nervosi_e_arbitro_severo_partita_calda_con_i_motivi():
    c = componenti.calore_partita(
        precedenti=[7, 6, 6, 7, 6], arbitro="Rossi", arbitro_medi=5.8, arbitro_partite=12,
        medie_squadre=(5.0, 4.8), media_lega=4.2,
    )
    assert c.calda and c.attesi >= 5.5
    assert "precedenti: 6,4 cartellini" in c.motivi
    assert "arbitro severo (Rossi): 5,8 cartellini a partita" in c.motivi


def test_partita_tranquilla_non_e_calda():
    c = componenti.calore_partita(
        precedenti=[3, 4, 4], arbitro_medi=3.9, arbitro_partite=20, medie_squadre=(4.0, 4.2),
        media_lega=4.2,
    )
    assert not c.calda and c.attesi < 4.5 and c.motivi == ()


def test_derby_e_sempre_caldo_anche_con_pochi_cartellini_e_senza_dati():
    c = componenti.calore_partita(derby="Derby: Inter – Milan", precedenti=[3, 3], media_lega=4.2)
    assert c.calda and c.attesi < componenti.SOGLIA_CARTELLINI_ATTESI
    assert c.motivi == ("Derby: Inter – Milan",)
    senza_dati = componenti.calore_partita(derby="Derby: Roma – Lazio")
    assert senza_dati.calda and senza_dati.attesi is None


def test_senza_dati_ne_derby_non_e_calda():
    c = componenti.calore_partita()
    assert not c.calda and c.attesi is None and c.motivi == ()


def test_campo_caldo_e_posta_alzano_i_cartellini_attesi():
    base = componenti.calore_partita(medie_squadre=(5.0, 5.0), media_lega=4.2)
    con = componenti.calore_partita(
        campo_caldo="Napoli in casa: 5,1 cartellini a partita contro 4,0 di media",
        medie_squadre=(5.0, 5.0), media_lega=4.2, posta=(("Napoli", "titolo"), ("Roma", "Europa")),
    )
    assert con.attesi == pytest.approx(base.attesi + componenti.BONUS_CAMPO_CALDO
                                       + 2 * componenti.BONUS_POSTA)
    assert con.motivi[0].startswith("campo caldo: Napoli in casa")
    assert "posta in classifica: Napoli (titolo)" in con.motivi


def test_arbitro_con_poche_partite_e_precedenti_singoli_non_contano():
    c = componenti.calore_partita(precedenti=[9], arbitro_medi=9.0, arbitro_partite=2,
                                  media_lega=4.2)
    assert c.attesi is None and not c.calda


# ---------------------------------------------------------------- calcolo dal DB

def _squadre(s):
    nomi = {1: "SSC Napoli", 2: "AS Roma", 3: "Alfa", 4: "Beta", 5: "Gamma", 6: "Delta"}
    s.add_all(Squadra(id=i, nome=n) for i, n in nomi.items())
    s.add(Giocatore(id=9000, nome="Giocatore di prova"))
    s.add(Arbitro(id=1, nome_normalizzato="rossi", nome_visualizzato="Rossi"))
    s.flush()


def _gioca(s, pid, data, casa, trasf, cartellini, arbitro=None, competizione=135):
    s.add(Partita(id=pid, data_utc=data, competizione_id=competizione, stagione=2026,
                  casa_id=casa, trasferta_id=trasf, arbitro_id=arbitro, gol_casa=1,
                  gol_trasferta=1, stato="FT", statistiche_scaricate=True))
    s.flush()
    s.add(Presenza(partita_id=pid, giocatore_id=9000, squadra_id=casa, gialli=cartellini))


def _futura(s, pid, data, casa, trasf, arbitro=None, competizione=135):
    s.add(Partita(id=pid, data_utc=data, competizione_id=competizione, stagione=2026,
                  casa_id=casa, trasferta_id=trasf, arbitro_id=arbitro, stato="NS"))
    s.flush()


def _scenario(s):
    _squadre(s)
    base = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    pid = 100
    for coppia, cartellini, arbitro in (((3, 4), 8, 1), ((5, 6), 3, None), ((1, 2), 3, None)):
        for i in range(5):
            casa, trasf = coppia if i % 2 else coppia[::-1]
            _gioca(s, pid, base + timedelta(days=pid - 100), casa, trasf, cartellini, arbitro)
            pid += 1
    _futura(s, 301, ORA + timedelta(days=2), 1, 2)  # derby Napoli-Roma, nomi con sigle
    _futura(s, 302, ORA + timedelta(days=3), 3, 4, arbitro=1)  # precedenti e arbitro nervosi
    _futura(s, 303, ORA + timedelta(days=3, hours=3), 5, 6)  # tranquilla
    _futura(s, 304, ORA + timedelta(days=40), 4, 3)  # nervosa, ma lontana


def test_calore_dal_db_derby_nervosa_e_tranquilla(sessione):
    _scenario(sessione)
    partite = sessione.query(Partita).filter(Partita.id >= 301).order_by(Partita.id).all()
    calore = componenti_calde.calore_partite(sessione, partite)
    derby, nervosa, tranquilla, lontana = (calore[i] for i in (301, 302, 303, 304))
    assert derby.calda and derby.motivi[0] == "Derby: SSC Napoli – AS Roma"
    assert nervosa.calda and nervosa.attesi >= 5.5
    assert "precedenti: 8,0 cartellini" in nervosa.motivi
    assert "arbitro severo (Rossi): 8,0 cartellini a partita" in nervosa.motivi
    assert not tranquilla.calda
    assert lontana.calda and lontana.attesi >= 5.5  # le partite future lontane contano


def test_nessuna_lista_manuale_e_necessaria(sessione):
    _scenario(sessione)
    assert sessione.query(ListaManuale).count() == 0
    righe = componenti_calde.partite_calde(sessione, ORA)
    assert [r.id for r in righe] == [301, 302, 304]  # per data
    r = righe[0]
    assert r.calda and r.derby and r.motivi[0].startswith("Derby: ") and r.attesi is not None


def test_partite_calde_solo_dei_campionati_chiesti_e_non_giocate(sessione):
    _scenario(sessione)
    _futura(sessione, 305, ORA + timedelta(days=1), 3, 4, competizione=140)  # Liga
    sessione.get(Partita, 302).stato = "PST"  # rinviata: fuori
    sessione.flush()
    assert [r.id for r in componenti_calde.partite_calde(sessione, ORA, (135,))] == [301, 304]
    assert [r.id for r in componenti_calde.partite_calde(sessione, ORA, (140,))] == [305]
    assert [r.id for r in componenti_calde.partite_calde(sessione, ORA + timedelta(days=10))] == [304]


def test_query_raggruppate_non_una_per_partita(sessione):
    _scenario(sessione)
    for i in range(30):
        _futura(sessione, 400 + i, ORA + timedelta(days=1 + i), 3 + i % 2, 4 - i % 2)
    engine = sessione.get_bind()
    conteggi = []

    def conta(*_):
        conteggi.append(1)

    event.listen(engine, "before_cursor_execute", conta)
    try:
        poche = sessione.query(Partita).filter(Partita.id.in_((301, 302))).all()
        molte = sessione.query(Partita).filter(Partita.id >= 301).all()
        del conteggi[:]
        componenti_calde.calore_partite(sessione, poche)
        n_poche = len(conteggi)
        del conteggi[:]
        componenti_calde.calore_partite(sessione, molte)
        n_molte = len(conteggi)
    finally:
        event.remove(engine, "before_cursor_execute", conta)
    assert len(molte) > 30 and n_molte == n_poche <= 8


def test_totali_cartellini_decimal_di_postgres_diventano_int():
    class Risultato:
        def all(self):
            return [(ORA, 1, 2, 135, 2026, None, Decimal("7"))]

    class SessioneDecimal:
        def execute(self, _):
            return Risultato()

    (giocata,) = componenti_calde._giocate(SessioneDecimal(), 2024, ORA)
    assert giocata.cartellini == 7 and isinstance(giocata.cartellini, int)


def test_separa_prossimi_7_giorni_dal_resto():
    def riga(i, giorni):
        return componenti.RigaPartita(
            id=i, quando="", giornata=None, casa="A", trasferta="B", arbitro=None, calda=True,
            formazioni="probabili", data_utc=ORA + timedelta(days=giorni),
        )

    righe = [riga(1, -1), riga(2, 0), riga(3, 7), riga(4, 8), riga(5, 90)]
    prossime, resto = componenti_calde.separa_prossimi_giorni(righe, ORA)
    assert [r.id for r in prossime] == [2, 3] and [r.id for r in resto] == [4, 5]


# ---------------------------------------------------------------- pagina

def _dati_pagina(s, adesso):
    s.add_all([Squadra(id=1, nome="SSC Napoli"), Squadra(id=2, nome="AS Roma"),
               Squadra(id=3, nome="Inter"), Squadra(id=4, nome="Milan"),
               Squadra(id=5, nome="Real Madrid"), Squadra(id=6, nome="FC Barcelona"),
               Squadra(id=7, nome="Quieta A"), Squadra(id=8, nome="Quieta B"),
               Squadra(id=9, nome="<b>Brutta</b>"), Squadra(id=10, nome="Cattiva")])
    s.flush()
    giorno = adesso.replace(hour=18, minute=45, second=0, microsecond=0)
    _futura(s, 1, giorno + timedelta(days=2), 1, 2)  # derby fra 2 giorni
    _futura(s, 2, giorno + timedelta(days=30), 3, 4)  # derby lontano
    _futura(s, 3, giorno + timedelta(days=3), 5, 6, competizione=140)  # derby Liga
    _futura(s, 4, giorno + timedelta(days=3), 7, 8)  # tranquilla
    s.add(ListaManuale(tipo="derby", squadra_a_id=9, squadra_b_id=10))  # riga manuale
    _futura(s, 5, giorno + timedelta(days=4), 9, 10)
    s.flush()


def test_pagina_prossimi_giorni_poi_resto_serie_a_predefinita(sessione_db):
    adesso = datetime.now(timezone.utc)
    with sessione_db() as s:
        _dati_pagina(s, adesso)
    at = avvia(PAGINA_CALDE)
    assert not at.exception
    t = visibile(at)
    assert "Prossimi 7 giorni" in t and "Il resto della stagione" in t
    assert t.index("Prossimi 7 giorni") < t.index("Il resto della stagione")
    schede = [m.value for m in at.markdown if 'class="cr-partita"' in m.value]
    assert len(schede) == 3  # Napoli-Roma, Inter-Milan e la manuale; non la Liga né la quieta
    assert "SSC Napoli" in schede[0] and "Derby: SSC Napoli – AS Roma" in schede[0]
    assert "Inter" in schede[2] and "Brutta" not in schede[2]
    # orario di Roma sulla scheda e giorni nelle intestazioni
    prima = adesso.replace(hour=18, minute=45, second=0, microsecond=0) + timedelta(days=2)
    assert f'<span class="cr-ora">{componenti.ora_italiana(prima)}</span>' in schede[0]
    assert len([x for x in at.subheader]) == 3


def test_pagina_nomi_con_html_escapati(sessione_db):
    adesso = datetime.now(timezone.utc)
    with sessione_db() as s:
        _dati_pagina(s, adesso)
    at = avvia(PAGINA_CALDE)
    html = "\n".join(m.value for m in at.markdown)
    assert "<b>Brutta</b>" not in html and "&lt;b&gt;Brutta&lt;/b&gt;" in html


def test_pagina_liga_con_il_filtro(sessione_db):
    adesso = datetime.now(timezone.utc)
    with sessione_db() as s:
        _dati_pagina(s, adesso)
    at = avvia(PAGINA_CALDE)
    at.segmented_control(key="scelta_campionato").set_value("Liga").run()
    assert not at.exception
    schede = [m.value for m in at.markdown if 'class="cr-partita"' in m.value]
    assert len(schede) == 1 and "Real Madrid" in schede[0] and "Derby" in schede[0]
    assert "Il resto della stagione" not in visibile(at)  # nessuna calda oltre i 7 giorni


def test_pagina_senza_partite_calde_non_si_rompe(sessione_db):
    with sessione_db() as s:
        s.add_all([Squadra(id=7, nome="Quieta A"), Squadra(id=8, nome="Quieta B")])
        s.flush()
        _futura(s, 4, datetime.now(timezone.utc) + timedelta(days=3), 7, 8)
    at = avvia(PAGINA_CALDE)
    assert not at.exception
    assert "Nessuna partita calda" in visibile(at)


def test_scheda_con_cartellini_attesi_e_motivi_escapati():
    import stile

    riga = componenti.RigaPartita(
        id=1, quando="", giornata=None, casa="A", trasferta="B", arbitro=None, calda=True,
        formazioni="probabili", ora="20:45", attesi=6.4,
        motivi=("Derby: <i>A</i> – B", "precedenti: 6,4 cartellini"),
    )
    h = stile.scheda_partita(riga)
    assert "6,4 cartellini attesi" in h and "precedenti: 6,4 cartellini" in h
    assert "<i>" not in h and "&lt;i&gt;" in h and "\n" not in h
    assert "cr-calore" not in stile.scheda_partita(
        componenti.RigaPartita(id=2, quando="", giornata=None, casa="A", trasferta="B",
                               arbitro=None, calda=False, formazioni="probabili"))


def test_pagina_seconda_visita_dalla_cache(sessione_db, monkeypatch):
    import streamlit as st

    st.cache_data.clear()
    adesso = datetime.now(timezone.utc)
    with sessione_db() as s:
        _dati_pagina(s, adesso)
    chiamate = []
    originale = componenti_calde.partite_calde

    def contata(*args, **kwargs):
        chiamate.append(1)
        return originale(*args, **kwargs)

    monkeypatch.setattr(componenti_calde, "partite_calde", contata)
    avvia(PAGINA_CALDE)
    avvia(PAGINA_CALDE)
    st.cache_data.clear()
    assert len(chiamate) == 1
