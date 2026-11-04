import pytest
from ayuda_app import PAGINA_IMPOSTAZIONI, avvia, sessione_db, url_db, visibile
from db_prova import CASA, TRASF, popola
from sqlalchemy import select

import componenti_giocate  # noqa: E402  (app/ è in sys.path grazie ad ayuda_app)
from ammonizioni.db import repo
from ammonizioni.db.modelli import Impostazione, ListaManuale, Partita, Squadra
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


def _liste(s, tipo):
    return [
        (r.squadra_a_id, r.squadra_b_id)
        for r in s.execute(select(ListaManuale).where(ListaManuale.tipo == tipo)).scalars()
    ]


def test_squadre_selezionabili_solo_serie_a_stagione_corrente(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        assert componenti_giocate.squadre_serie_a(s) == [
            (CASA, "Casa FC"), (TERZA, "Terza FC"), (TRASF, "Trasferta FC"),
        ]


def test_aggiungi_derby_persistito(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    assert not at.exception
    at.selectbox(key="derby_a").select(CASA)
    at.selectbox(key="derby_b").select(TERZA)
    at.button(key="aggiungi_derby").click().run()
    assert not at.exception
    assert not at.error
    with sessione_db() as s:
        assert sorted(_liste(s, "derby")) == sorted([(TRASF, CASA), (CASA, TERZA)])
    assert "Casa FC – Terza FC" in visibile(at)


def test_derby_duplicato_anche_a_squadre_invertite_rifiutato(sessione_db):
    with sessione_db() as s:
        _prepara(s)  # il seed ha già il derby (TRASF, CASA)
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.selectbox(key="derby_a").select(CASA)
    at.selectbox(key="derby_b").select(TRASF)
    at.button(key="aggiungi_derby").click().run()
    assert not at.exception
    assert any("già presente" in e.value for e in at.error)
    with sessione_db() as s:
        assert len(_liste(s, "derby")) == 1


def test_derby_con_stessa_squadra_rifiutato(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.selectbox(key="derby_a").select(CASA)
    at.selectbox(key="derby_b").select(CASA)
    at.button(key="aggiungi_derby").click().run()
    assert any("diverse" in e.value for e in at.error)
    with sessione_db() as s:
        assert len(_liste(s, "derby")) == 1


def test_rimuovi_derby(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        riga_id = s.execute(select(ListaManuale.id)).scalar_one()
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.button(key=f"rimuovi_lista_{riga_id}").click().run()
    assert not at.exception
    with sessione_db() as s:
        assert _liste(s, "derby") == []


def test_aggiungi_e_rimuovi_campo_caldo(sessione_db):
    with sessione_db() as s:
        _prepara(s)
    at = avvia(PAGINA_IMPOSTAZIONI)
    at.selectbox(key="campo_caldo_squadra").select(TERZA)
    at.button(key="aggiungi_campo_caldo").click().run()
    assert not at.exception
    with sessione_db() as s:
        assert _liste(s, "campo_caldo") == [(TERZA, None)]
        riga_id = s.execute(select(ListaManuale.id).where(ListaManuale.tipo == "campo_caldo")).scalar_one()
    # di nuovo la stessa squadra: rifiutata
    at.selectbox(key="campo_caldo_squadra").select(TERZA)
    at.button(key="aggiungi_campo_caldo").click().run()
    assert any("già presente" in e.value for e in at.error)
    at.button(key=f"rimuovi_lista_{riga_id}").click().run()
    with sessione_db() as s:
        assert _liste(s, "campo_caldo") == []


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


def test_maschera_chiave_corta():
    assert componenti_giocate.maschera_chiave("ab") == "••••"
    assert componenti_giocate.maschera_chiave("") == "non impostata"
    assert componenti_giocate.maschera_chiave(None) == "non impostata"
    assert componenti_giocate.maschera_chiave("12345678") == "••••5678"
