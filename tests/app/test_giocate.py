from datetime import date, datetime, timedelta, timezone

import pytest
from zoneinfo import ZoneInfo

from ayuda_app import PAGINA_GIOCATE, avvia, sessione_db, url_db, visibile
from db_prova import CASA, TRASF, popola
from sqlalchemy import select

import componenti_giocate  # noqa: E402  (app/ è in sys.path grazie ad ayuda_app)

from ammonizioni.db.modelli import Giocata, Giocatore, Partita, Squadra

PARTITA_VICINA = 200
PARTITA_LONTANA = 201


def _prepara(s):
    """Dati di prova più due partite relative a oggi: una tra 1 giorno, una tra 30."""
    popola(s)
    adesso = datetime.now(timezone.utc)
    for pid, giorni in ((PARTITA_VICINA, 1), (PARTITA_LONTANA, 30)):
        s.add(
            Partita(
                id=pid, data_utc=adesso + timedelta(days=giorni), competizione_id=135,
                stagione=2026, giornata=20, casa_id=CASA, trasferta_id=TRASF, stato="NS",
            )
        )
    s.flush()


def _tabella(at, prima_colonna):
    for d in at.dataframe:
        if d.value.columns[0] == prima_colonna:
            return d.value
    raise AssertionError(f"tabella con prima colonna {prima_colonna!r} non trovata")


def _compila(at, *, quota="2,10", puntata="10", fonte="io", tipster=""):
    at.selectbox(key="giocata_fonte").select(fonte)
    if tipster:
        at.text_input(key="giocata_tipster").set_value(tipster)
    at.text_input(key="giocata_quota").set_value(quota)
    at.text_input(key="giocata_puntata").set_value(puntata)
    return at


def test_registra_giocata_e_compare_nel_registro(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE)
    assert not at.exception
    at.selectbox(key="giocata_partita").select(PARTITA_VICINA).run()
    at.selectbox(key="giocata_giocatore").select(12).run()
    _compila(at, quota="2,10", puntata="10,50").run()
    at.button(key="salva_giocata").click().run()
    assert not at.exception
    assert not at.error
    with sessione_db() as s:
        g = s.execute(select(Giocata)).scalar_one()
        assert (g.partita_id, g.giocatore_id, g.fonte) == (PARTITA_VICINA, 12, "io")
        assert (g.quota, g.puntata, g.esito) == (2.1, 10.5, "in_attesa")
        assert g.data == datetime.now(ZoneInfo("Europe/Rome")).date()
    df = _tabella(at, "Data")
    assert list(df.columns) == ["Data", "Partita", "Giocatore", "Fonte", "Quota", "Puntata", "Esito"]
    riga = df.iloc[0]
    assert riga["Partita"] == "Casa FC – Trasferta FC"
    assert riga["Giocatore"] == "Terzino Casa"
    assert riga["Fonte"] == "io"
    assert riga["Quota"] == "2,10"
    assert riga["Puntata"] == "10,50 €"
    assert riga["Esito"] == "in attesa"


def test_partite_proposte_solo_nella_finestra_di_sette_giorni(sessione_db):
    with sessione_db() as s:
        popola(s)
        ora = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        # partite del seed: giornata 5 il 6/10, giornata 6 il 13/10 (nel passato di 7 giorni), futura l'8/11
        s.add(Partita(id=300, data_utc=ora + timedelta(days=6), competizione_id=135, stagione=2026,
                      casa_id=CASA, trasferta_id=TRASF, stato="NS"))
        s.add(Partita(id=301, data_utc=ora + timedelta(days=8), competizione_id=135, stagione=2026,
                      casa_id=CASA, trasferta_id=TRASF, stato="NS"))
        s.add(Partita(id=302, data_utc=ora + timedelta(days=3), competizione_id=137, stagione=2026,
                      casa_id=CASA, trasferta_id=TRASF, stato="NS"))
        s.flush()
        proposte = componenti_giocate.partite_selezionabili(s, ora)
        ids = [i for i, _ in proposte]
        assert 300 in ids and 6 in ids  # 6 = 13/10, una settimana prima
        assert 301 not in ids and 302 not in ids  # fuori finestra / non Serie A
        assert 1 not in ids  # troppo vecchia
        assert ids == sorted(ids, key=lambda i: s.get(Partita, i).data_utc)
        assert componenti_giocate.partite_selezionabili(s, ora, includi=1)[0][0] == 1
        etichetta = dict(proposte)[300]
        assert "Casa FC – Trasferta FC" in etichetta


PARTITA_LIGA = 210


def _aggiungi_liga(s):
    """Partita di Liga tra 2 giorni e una giocata su di essa; una giocata anche su una Serie A."""
    s.add_all([Squadra(id=501, nome="Real Liga"), Squadra(id=502, nome="Barca Liga")])
    s.add_all([Giocatore(id=511, nome="Punta Real", ruolo="F"),
               Giocatore(id=521, nome="Punta Barca", ruolo="F")])
    s.flush()
    s.add(Partita(id=PARTITA_LIGA, data_utc=datetime.now(timezone.utc) + timedelta(days=2),
                  competizione_id=140, stagione=2026, casa_id=501, trasferta_id=502, stato="NS"))
    s.flush()


def test_partite_selezionabili_per_campionato(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        _aggiungi_liga(s)
        ora = datetime.now(timezone.utc)
        serie_a = [i for i, _ in componenti_giocate.partite_selezionabili(s, ora)]  # predefinito
        liga = componenti_giocate.partite_selezionabili(s, ora, campionati=(140,))
        tutte = componenti_giocate.partite_selezionabili(s, ora, campionati=(135, 140))
        assert PARTITA_LIGA not in serie_a and PARTITA_VICINA in serie_a
        assert [i for i, _ in liga] == [PARTITA_LIGA]
        assert "Real Liga – Barca Liga" in liga[0][1]
        assert {PARTITA_LIGA, PARTITA_VICINA} <= {i for i, _ in tutte}
        # con piu' campionati l'etichetta dice di quale
        assert dict(tutte)[PARTITA_LIGA].startswith("Liga · ")
        assert dict(tutte)[PARTITA_VICINA].startswith("Serie A · ")


def test_pagina_giocate_filtro_predefinito_serie_a(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        _aggiungi_liga(s)
    at = avvia(PAGINA_GIOCATE)
    assert not at.exception
    assert at.radio(key="filtro_giocate").value == "Serie A"
    # le opzioni sono le etichette "gg/mm hh:mm Casa – Trasferta"
    opzioni = " | ".join(at.selectbox(key="giocata_partita").options)
    assert "Casa FC – Trasferta FC" in opzioni and "Real Liga" not in opzioni

    at.radio(key="filtro_giocate").set_value("Liga").run()
    assert not at.exception
    opzioni = at.selectbox(key="giocata_partita").options
    assert len(opzioni) == 1 and "Real Liga – Barca Liga" in opzioni[0]

    at.radio(key="filtro_giocate").set_value("Tutti").run()
    assert not at.exception
    opzioni = " | ".join(at.selectbox(key="giocata_partita").options)
    assert "Liga · " in opzioni and "Serie A · " in opzioni


def test_registro_filtrato_per_campionato(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        _aggiungi_liga(s)
        # una giocata su una partita di Serie A, una su una di Liga, una su una Champions
        s.add(Partita(id=211, data_utc=datetime.now(timezone.utc) + timedelta(days=3),
                      competizione_id=2, stagione=2026, casa_id=CASA, trasferta_id=TRASF, stato="NS"))
        s.flush()
        for pid, gid in ((PARTITA_VICINA, 12), (PARTITA_LIGA, 511), (211, 12)):
            s.add(Giocata(data=date(2026, 11, 5), partita_id=pid, giocatore_id=gid, fonte="io",
                          quota=2.0, puntata=10.0))
        s.flush()
        partite = lambda righe: sorted(r["Partita"] for r in righe)  # noqa: E731
        assert partite(componenti_giocate.righe_registro(s)) == ["Casa FC – Trasferta FC"]
        assert partite(componenti_giocate.righe_registro(s, campionati=(140,))) == [
            "Real Liga – Barca Liga"
        ]
        assert len(componenti_giocate.righe_registro(s, campionati=None)) == 3  # tutte, anche la Champions


def test_giocatori_proposti_sono_quelli_delle_due_squadre(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE)
    at.selectbox(key="giocata_partita").select(PARTITA_VICINA).run()
    sel = at.selectbox(key="giocata_giocatore")
    assert len(sel.options) == 8
    for gid in (11, 12, 21, 24):
        sel.select(gid)  # non solleva: l'id è tra le opzioni


@pytest.mark.parametrize("puntata", ["0", "-5", "abc", ""])
def test_puntata_zero_rifiutata(sessione_db, puntata):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE)
    at.selectbox(key="giocata_partita").select(PARTITA_VICINA).run()
    _compila(at, puntata=puntata).run()
    at.button(key="salva_giocata").click().run()
    assert not at.exception
    assert any("untata" in e.value for e in at.error)
    with sessione_db() as s:
        assert s.execute(select(Giocata)).first() is None


def test_quota_non_valida_rifiutata(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE)
    at.selectbox(key="giocata_partita").select(PARTITA_VICINA).run()
    _compila(at, quota="1").run()
    at.button(key="salva_giocata").click().run()
    assert not at.exception
    assert any("Quota non valida" in e.value for e in at.error)
    with sessione_db() as s:
        assert s.execute(select(Giocata)).first() is None


def test_fonte_tipster_salva_il_nome(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE)
    at.selectbox(key="giocata_partita").select(PARTITA_VICINA).run()
    _compila(at, fonte="tipster", tipster="Luca").run()
    at.button(key="salva_giocata").click().run()
    assert not at.exception
    assert not at.error
    with sessione_db() as s:
        assert s.execute(select(Giocata.fonte)).scalar_one() == "Luca"


def test_fonte_tipster_senza_nome_rifiutata(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE)
    at.selectbox(key="giocata_partita").select(PARTITA_VICINA).run()
    _compila(at, fonte="tipster").run()
    at.button(key="salva_giocata").click().run()
    assert any("tipster" in e.value for e in at.error)
    with sessione_db() as s:
        assert s.execute(select(Giocata)).first() is None


def test_campi_precompilati_dai_parametri_url(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE, partita=PARTITA_VICINA, giocatore=23)
    assert not at.exception
    assert at.selectbox(key="giocata_partita").value == PARTITA_VICINA
    assert at.selectbox(key="giocata_giocatore").value == 23


def test_parametri_url_non_validi_ignorati(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_GIOCATE, partita="abc", giocatore="xyz")
    assert not at.exception


def test_partita_senza_giocatori_niente_form_e_niente_eccezioni(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        s.add(Squadra(id=7, nome="Vuota A"))
        s.add(Squadra(id=8, nome="Vuota B"))
        s.flush()
        s.add(Partita(id=210, data_utc=datetime.now(timezone.utc) + timedelta(days=2),
                      competizione_id=135, stagione=2026, casa_id=7, trasferta_id=8, stato="NS"))
    at = avvia(PAGINA_GIOCATE)
    at.selectbox(key="giocata_partita").select(210).run()
    assert not at.exception
    assert "Nessun giocatore disponibile per questa partita" in visibile(at)
    assert len(at.button) == 0
    with sessione_db() as s:
        assert s.execute(select(Giocata)).first() is None


def test_aggiungi_giocata_rifiuta_id_mancanti(sessione_db):
    from ammonizioni.giocate.registro import aggiungi_giocata

    with sessione_db() as s:
        _prepara(s)
        with pytest.raises(ValueError, match="giocatore"):
            aggiungi_giocata(s, PARTITA_VICINA, None, "io", 2.0, 10, date(2026, 11, 4))
        with pytest.raises(ValueError, match="partita"):
            aggiungi_giocata(s, None, 12, "io", 2.0, 10, date(2026, 11, 4))


def test_nessuna_partita_mostra_messaggio(sessione_db):
    at = avvia(PAGINA_GIOCATE)
    assert not at.exception
    assert "Nessuna partita" in visibile(at)


def test_registro_piu_recente_per_primo(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        s.add(Giocata(data=date(2026, 10, 1), partita_id=1, giocatore_id=12, fonte="io",
                      quota=2.0, puntata=5, esito="vinta"))
        s.add(Giocata(data=date(2026, 10, 20), partita_id=2, giocatore_id=22, fonte="modello",
                      quota=3.0, puntata=5, esito="persa"))
    at = avvia(PAGINA_GIOCATE)
    df = _tabella(at, "Data")
    assert list(df["Data"]) == ["20/10/2026", "01/10/2026"]
    assert list(df["Esito"]) == ["persa", "vinta"]


def test_statistiche_per_fonte_mostrate(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        s.add(Giocata(data=date(2026, 10, 1), partita_id=1, giocatore_id=12, fonte="io",
                      quota=2.5, puntata=10, esito="vinta"))
        s.add(Giocata(data=date(2026, 10, 2), partita_id=2, giocatore_id=22, fonte="io",
                      quota=2.5, puntata=10, esito="persa"))
        s.add(Giocata(data=date(2026, 10, 3), partita_id=3, giocatore_id=12, fonte="io",
                      quota=2.5, puntata=10, esito="in_attesa"))
    at = avvia(PAGINA_GIOCATE)
    assert not at.exception
    df = _tabella(at, "Fonte")
    assert list(df.columns) == [
        "Fonte", "Giocate", "Successo", "Prob. implicita media", "Profitto", "Rendimento",
    ]
    riga = df.iloc[0]
    assert riga["Fonte"] == "io"
    assert riga["Giocate"] == 2
    assert riga["Successo"] == "50%"
    assert riga["Prob. implicita media"] == "40%"
    assert riga["Profitto"] == "5,00 €"
    assert riga["Rendimento"] == "25%"
