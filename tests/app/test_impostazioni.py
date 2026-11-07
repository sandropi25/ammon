import pytest
from ayuda_app import PAGINA_DETTAGLIO, PAGINA_IMPOSTAZIONI, avvia, sessione_db, url_db, visibile
from db_prova import CASA, PARTITA_FUTURA, popola

import componenti_giocate  # noqa: E402  (app/ è in sys.path grazie ad ayuda_app)
from ammonizioni.db import repo
from ammonizioni.db.modelli import Impostazione, Partita, Squadra
from ammonizioni.motore.pesi import Pesi, carica_pesi, salva_pesi

TERZA = 3


def _prepara(s):
    popola(s)
    s.add(Squadra(id=TERZA, nome="Terza FC"))
    s.add(Squadra(id=4, nome="Straniera FC"))  # senza partite di Serie A: non selezionabile
    s.flush()
    s.add(Partita(id=50, data_utc=s.get(Partita, 1).data_utc, competizione_id=135, stagione=2026,
                  casa_id=TERZA, trasferta_id=CASA, stato="FT"))
    s.add(Partita(id=51, data_utc=s.get(Partita, 1).data_utc, competizione_id=135, stagione=2025,
                  casa_id=4, trasferta_id=CASA, stato="FT"))
    s.flush()


def test_derby_e_campi_caldi_in_sola_lettura_senza_moduli_di_inserimento(sessione_db):
    with sessione_db() as s:
        _prepara(s)  # il seed ha il derby manuale Casa FC - Trasferta FC
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    assert not at.selectbox  # niente selettori di squadre
    assert not {b.key for b in at.button} & {"aggiungi_derby", "aggiungi_campo_caldo"}
    t = visibile(at)
    assert "Derby e rivalità" in t and "Campi caldi" in t
    assert "Trasferta FC – Casa FC" in t  # la riga manuale resta valida e si vede
    assert "Nessun campo caldo calcolato" in t


def test_derby_predefinito_e_campo_caldo_calcolato_con_il_motivo(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        s.add_all([Squadra(id=300, nome="FC Internazionale Milano"), Squadra(id=301, nome="AC Milan")])
        s.flush()
        _storia_campo_caldo(s, squadra=CASA)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    t = visibile(at)
    assert "FC Internazionale Milano – AC Milan" in t and "Serie A" in t
    assert "Casa FC in casa: 6,0 cartellini a partita contro 4,5 di media" in t


def _storia_campo_caldo(s, squadra):
    """In Liga: 16 partite in casa di `squadra` con 6 cartellini ciascuna e 16 di altre
    squadre con 3: media del campionato 4,5, la squadra sta al +33%."""
    from datetime import datetime, timedelta, timezone

    from ammonizioni.db.modelli import Giocatore, Partita, Presenza

    altre = [Squadra(id=400 + i, nome=f"Altra {i}") for i in range(2)]
    s.add_all(altre)
    s.add(Giocatore(id=900, nome="Pippo"))
    s.flush()
    base = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    pid = 1000
    for i in range(32):
        casa, trasf, gialli = (squadra, 400, 6) if i < 16 else (401, 400, 3)
        s.add(Partita(id=pid, data_utc=base + timedelta(days=i), competizione_id=140,
                      stagione=2026, casa_id=casa, trasferta_id=trasf, stato="FT",
                      statistiche_scaricate=True))
        s.flush()
        s.add(Presenza(partita_id=pid, giocatore_id=900, squadra_id=casa, gialli=gialli))
        pid += 1


def test_modifica_peso_persistita_e_ripristino(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    assert at.number_input(key="peso_rivalita").value == pytest.approx(1.20)
    assert at.number_input(key="peso_soglia_partite_arbitro").value == 5
    at.number_input(key="peso_rivalita").set_value(1.35)
    at.number_input(key="peso_soglia_partite_arbitro").set_value(8)
    at.text_input(key="peso_pesi_stagioni").set_value("0.5, 0.3, 0.2")
    at.button(key="salva_pesi").click().run()
    assert not at.exception
    assert not at.error
    with sessione_db() as s:
        pesi = carica_pesi(s)
    assert pesi.rivalita == pytest.approx(1.35)
    assert pesi.soglia_partite_arbitro == 8
    assert pesi.pesi_stagioni == (0.5, 0.3, 0.2)
    assert pesi.campo_caldo == Pesi().campo_caldo  # il resto invariato
    assert at.number_input(key="peso_rivalita").value == pytest.approx(1.35)

    at.button(key="ripristina_pesi").click().run()
    assert not at.exception
    with sessione_db() as s:
        assert carica_pesi(s) == Pesi()
    assert at.number_input(key="peso_rivalita").value == pytest.approx(1.20)
    assert at.text_input(key="peso_pesi_stagioni").value == "0.6, 0.3, 0.1"


def test_un_campo_per_ogni_peso_scalare(sessione_db):
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    scalari = {n for n, v in Pesi().__dict__.items() if not isinstance(v, tuple)}
    assert {n.key for n in at.number_input} == {f"peso_{n}" for n in scalari}
    tuple_ = {"pesi_stagioni", "limiti_fattore", "limiti_probabilita", "soglie_diffida"}
    assert {t.key for t in at.text_input if t.key.startswith("peso_")} == {f"peso_{n}" for n in tuple_}


@pytest.mark.parametrize(
    "campo, testo",
    [
        ("pesi_stagioni", "0.5, 0.5"),         # numero di valori sbagliato
        ("limiti_fattore", "a, b"),            # non numerico
        ("soglie_diffida", "4, 9.5, 13"),      # soglie non intere
        ("soglie_diffida", ""),                # vuoto
        ("limiti_probabilita", "0, 0.7"),      # minimo non > 0
        ("limiti_probabilita", "0.02, 1"),     # massimo non < 1
        ("limiti_probabilita", "0.5, 0.3"),    # ordine invertito
    ],
)
def test_tuple_non_valide_rifiutate_senza_salvare(sessione_db, campo, testo):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.number_input(key="peso_rivalita").set_value(1.35)
    at.text_input(key=f"peso_{campo}").set_value(testo)
    at.button(key="salva_pesi").click().run()
    assert not at.exception
    assert len(at.error) == 1
    with sessione_db() as s:
        assert s.get(Impostazione, "pesi") is None


def test_peso_scalare_negativo_rifiutato():
    scalari = {n: getattr(Pesi(), n) for n, _ in componenti_giocate.campi_pesi()[0]}
    testi = {n: componenti_giocate.testo_tupla(getattr(Pesi(), n)) for n in componenti_giocate.campi_pesi()[1]}
    assert componenti_giocate.costruisci_pesi(scalari, testi) == Pesi()
    scalari["rivalita"] = -0.5
    with pytest.raises(ValueError, match="negativo"):
        componenti_giocate.costruisci_pesi(scalari, testi)


@pytest.mark.parametrize(
    "campo, valore",
    [
        ("minuti_prior", 0),          # ZeroDivisionError nel restringimento al ruolo
        ("bonus_ritardo", 0),         # math domain error nelle motivazioni
        ("rivalita", 0),
        ("diffidato", 0),
        ("soglia_partite_arbitro", 0),
        ("soglia_precedenti", 0),
        ("pesi_stagioni", "0, 0, 0"),  # ZeroDivisionError sui pesi stagionali
        ("limiti_fattore", "0, 1.6"),  # log(0) nelle motivazioni
    ],
)
def test_pesi_che_bloccano_il_motore_rifiutati(campo, valore):
    scalari = {n: getattr(Pesi(), n) for n, _ in componenti_giocate.campi_pesi()[0]}
    testi = {n: componenti_giocate.testo_tupla(getattr(Pesi(), n)) for n in componenti_giocate.campi_pesi()[1]}
    if isinstance(valore, str):
        testi[campo] = valore
    else:
        scalari[campo] = valore
    with pytest.raises(ValueError, match=campo):
        componenti_giocate.costruisci_pesi(scalari, testi)


def test_pesi_che_bloccano_il_motore_rifiutati_dalla_pagina(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.number_input(key="peso_minuti_prior").set_value(0.0)
    at.button(key="salva_pesi").click().run()
    assert not at.exception
    assert any("minuti_prior" in e.value for e in at.error)
    with sessione_db() as s:
        assert s.get(Impostazione, "pesi") is None


def test_dettaglio_non_si_blocca_con_pesi_non_validi_nel_db(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        repo.scrivi_impostazione(
            s, "pesi", {"minuti_prior": 0, "bonus_ritardo": 0, "pesi_stagioni": [0, 0, 0]}
        )
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    assert len(at.dataframe[0].value) > 0


def test_scelta_del_modello_v1_predefinito_e_v2_salvato(sessione_db):
    from ammonizioni.motore import modello

    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    assert at.radio(key="modello_scelto").value == "V2"
    t = visibile(at)
    assert "Coefficienti V2 stimati il 07/11/2026 su 1516 partite" in t
    at.radio(key="modello_scelto").set_value("V1").run()
    assert not at.exception
    with sessione_db() as s:
        assert modello.modello_scelto(s) == "V1"
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert at.radio(key="modello_scelto").value == "V1"


def test_dettaglio_con_v2_mostra_i_candidati(sessione_db):
    from ammonizioni.motore import modello

    with sessione_db() as s:
        _prepara(s)
        modello.salva_modello(s, "V2")
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    assert len(at.dataframe[0].value) > 0


def test_tuple_con_virgola_decimale_e_punto_e_virgola():
    assert componenti_giocate.tupla_da_testo("0,5; 0,3; 0,2", float, 3) == (0.5, 0.3, 0.2)
    assert componenti_giocate.tupla_da_testo("4, 9, 13", int) == (4, 9, 13)
    assert componenti_giocate.tupla_da_testo("0.7,1.6", float, 2) == (0.7, 1.6)


def test_chiave_api_mascherata(sessione_db, monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert "non impostata" in visibile(at)
    at.text_input(key="chiave_api_nuova").set_value("abcd-segreto-1234")
    at.button(key="salva_chiave_api").click().run()
    assert not at.exception
    assert not at.error
    with sessione_db() as s:
        assert repo.leggi_impostazione(s, "chiave_api") == "abcd-segreto-1234"
    t = visibile(at)
    assert "••••1234" in t
    assert "segreto" not in t
    assert "abcd-segreto-1234" not in "".join(str(w.value) for w in at.text_input)


def test_chiave_api_vuota_rifiutata(sessione_db, monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.button(key="salva_chiave_api").click().run()
    assert any("chiave" in e.value.lower() for e in at.error)
    with sessione_db() as s:
        assert repo.leggi_impostazione(s, "chiave_api") is None


def test_chiave_api_variabile_ambiente_ha_precedenza(sessione_db, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "da-ambiente")
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert "variabile d'ambiente" in visibile(at)
    assert "da-ambiente" not in visibile(at)


def test_chiave_football_data_mascherata(sessione_db, monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_KEY", raising=False)
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert "Chiave football-data.org" in "".join(h.value for h in at.header)
    at.text_input(key="chiave_football_data_nuova").set_value("fd-segreto-9876")
    at.button(key="salva_chiave_football_data").click().run()
    assert not at.exception
    assert not at.error
    with sessione_db() as s:
        assert repo.leggi_impostazione(s, "chiave_football_data") == "fd-segreto-9876"
        assert repo.leggi_impostazione(s, "chiave_api") is None
    t = visibile(at)
    assert "••••9876" in t
    assert "segreto" not in t
    assert "fd-segreto-9876" not in "".join(str(w.value) for w in at.text_input)


def test_chiave_football_data_vuota_rifiutata(sessione_db, monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_KEY", raising=False)
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.button(key="salva_chiave_football_data").click().run()
    assert any("chiave" in e.value.lower() for e in at.error)
    with sessione_db() as s:
        assert repo.leggi_impostazione(s, "chiave_football_data") is None


def test_chiave_football_data_variabile_ambiente_ha_precedenza(sessione_db, monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "da-ambiente")
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert "FOOTBALL_DATA_KEY" in visibile(at)
    assert "da-ambiente" not in visibile(at)


def test_chiave_api_football_etichettata_solo_se_fonte_api_football(sessione_db):
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert any("FONTE_DATI=api_football" in h.value for h in at.header)


def test_maschera_chiave_corta():
    assert componenti_giocate.maschera_chiave("ab") == "••••"
    assert componenti_giocate.maschera_chiave("") == "non impostata"
    assert componenti_giocate.maschera_chiave(None) == "non impostata"
    assert componenti_giocate.maschera_chiave("12345678") == "••••5678"
