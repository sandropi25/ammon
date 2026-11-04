import pytest
from ayuda_app import PAGINA_DETTAGLIO, avvia, sessione_db, url_db, visibile
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola
from sqlalchemy import select

from ammonizioni.db.modelli import DuelloManuale, Formazione, Giocatore, Segnalazione


def _riga(at, nome):
    df = at.dataframe[0].value
    return df[df["Giocatore"] == nome].iloc[0]


def _percentuali(df):
    return [int(x.rstrip("%")) for x in df["Probabilità"]]


def test_partita_mancante_o_sconosciuta_mostra_messaggio(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO)
    assert not at.exception
    assert "Nessuna partita selezionata" in visibile(at)
    at = avvia(PAGINA_DETTAGLIO, partita=9999)
    assert not at.exception
    assert "Partita non trovata" in visibile(at)
    at = avvia(PAGINA_DETTAGLIO, partita="abc")
    assert not at.exception
    assert "Partita non trovata" in visibile(at)


def test_dettaglio_mostra_classifica_ordinata(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    df = at.dataframe[0].value
    assert list(df.columns) == [
        "Giocatore", "Squadra", "Probabilità", "Motivazioni", "Affidabilità",
        "Quota", "Implicita", "Valore", "Tipster",
    ]
    assert len(df) == 6  # 8 titolari meno i due portieri
    perc = _percentuali(df)
    assert perc == sorted(perc, reverse=True)
    assert "Portiere Casa" not in set(df["Giocatore"])
    t = visibile(at)
    assert "Casa FC" in t and "Trasferta FC" in t
    assert "Arbitro: Rossi" in t
    # caratteri non ASCII (niente mojibake)
    assert "Casa FC – Trasferta FC" in [h.value for h in at.header]
    assert "· Giornata 7 · formazioni ufficiali" in t
    assert any(e.label.startswith("Terzino Casa (Casa FC) · ") for e in at.expander)
    assert "Rivalità" in t


def test_quota_con_virgola_accettata_e_valore_mostrato(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    at.text_input(key="quota_12").set_value("2,10")
    at.button(key="salva_quota_12").click().run()
    assert not at.exception
    assert not at.error
    riga = _riga(at, "Terzino Casa")
    assert riga["Quota"] == "2,10"
    assert riga["Implicita"] == "48%"
    assert riga["Valore"].endswith("%") and riga["Valore"][0] in "+-"
    assert _riga(at, "Terzino Trasf")["Quota"] == ""
    # la quota resta in sessione, non nel DB
    with sessione_db() as s:
        assert s.execute(select(Segnalazione)).first() is None


@pytest.mark.parametrize("quota", ["abc", "1", "0", ""])
def test_quota_non_valida_mostra_errore_senza_eccezioni(sessione_db, quota):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    at.text_input(key="quota_12").set_value(quota)
    at.button(key="salva_quota_12").click().run()
    assert not at.exception
    assert any("Quota non valida" in e.value for e in at.error)
    assert _riga(at, "Terzino Casa")["Quota"] == ""


def test_segnalazione_tipster_salvata_e_mostrata(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    at.text_input(key="tipster_nome").set_value("Luca")
    at.selectbox(key="tipster_giocatore").select(13)
    at.button(key="salva_tipster").click().run()
    assert not at.exception
    with sessione_db() as s:
        riga = s.execute(select(Segnalazione)).scalar_one()
        assert (riga.partita_id, riga.giocatore_id, riga.fonte) == (PARTITA_FUTURA, 13, "Luca")
    assert _riga(at, "Centrocampista Casa")["Tipster"] == "Luca"


def test_tipster_senza_nome_mostra_errore(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    at.button(key="salva_tipster").click().run()
    assert not at.exception
    assert any("nome del tipster" in e.value for e in at.error)


def test_duello_manuale_scritto_nel_db(sessione_db):
    with sessione_db() as s:
        popola(s)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    at.selectbox(key="duello_12").select(23).run()
    assert not at.exception
    with sessione_db() as s:
        riga = s.execute(select(DuelloManuale)).scalar_one()
        assert (riga.partita_id, riga.giocatore_id, riga.avversario_id) == (PARTITA_FUTURA, 12, 23)
    assert at.selectbox(key="duello_12").value == 23


def test_duello_manuale_annullabile_con_nessuno(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.add(DuelloManuale(partita_id=PARTITA_FUTURA, giocatore_id=12, avversario_id=23))
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert at.selectbox(key="duello_12").value == 23
    at.selectbox(key="duello_12").select_index(0).run()  # la prima opzione è "(nessuno)"
    assert not at.exception
    with sessione_db() as s:
        assert s.execute(select(DuelloManuale)).first() is None
    # torna l'avversario automatico (non resta "(nessuno)")
    assert at.selectbox(key="duello_12").value is not None


def test_riepilogo_cambi_con_ufficiali(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.add(Giocatore(id=99, nome="Panchinaro Casa", ruolo="D"))
        s.flush()
        for sq, gid in [(CASA, 11), (CASA, 12), (CASA, 13), (CASA, 99), (TRASF, 21)]:
            s.add(Formazione(partita_id=PARTITA_FUTURA, squadra_id=sq, giocatore_id=gid, tipo="probabile"))
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    t = visibile(at)
    assert "Casa FC: entrati Punta Casa; usciti Panchinaro Casa" in t


def test_probabili_correggibili_con_multiselect(sessione_db):
    with sessione_db() as s:
        popola(s, con_formazione=False)
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    assert sorted(at.multiselect(key=f"probabili_{CASA}").value) == [11, 12, 13, 14]
    at.multiselect(key=f"probabili_{CASA}").set_value([11, 12, 13])
    at.button(key="salva_probabili").click().run()
    assert not at.exception
    with sessione_db() as s:
        righe = s.execute(
            select(Formazione.squadra_id, Formazione.giocatore_id).where(
                Formazione.partita_id == PARTITA_FUTURA, Formazione.tipo == "probabile"
            )
        ).all()
    assert sorted(g for sq, g in righe if sq == CASA) == [11, 12, 13]
    assert sorted(g for sq, g in righe if sq == TRASF) == [21, 22, 23, 24]
    # candidati dopo la correzione: 12, 13 (casa) + 22, 23, 24 (trasferta); i portieri sono esclusi
    assert len(at.dataframe[0].value) == 5
