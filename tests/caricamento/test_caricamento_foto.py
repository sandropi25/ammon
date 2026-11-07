"""Caricamento delle foto: chi si cerca, in che ordine, cosa si salva (client finto)."""
from datetime import datetime, timedelta, timezone

import httpx

from ammonizioni.caricamento import foto as caricamento
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti import foto as fonti_foto

ADESSO = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
URL = "https://r2.thesportsdb.com/c/{}.png"


def client_finto(risposta=None, richieste=None, codice=200):
    """Risponde con un giocatore dal nome cercato (o 429 dopo `codice`)."""
    def gestore(richiesta):
        nome = richiesta.url.params["p"]
        if richieste is not None:
            richieste.append(nome)
        if codice != 200:
            return httpx.Response(codice)
        if risposta is not None and nome not in risposta:
            return httpx.Response(200, json={"player": None})
        return httpx.Response(200, json={"player": [{
            "strPlayer": nome, "strSport": "Soccer", "strTeam": "Inter",
            "strCutout": URL.format(nome.replace(" ", "_")),
        }]})
    return fonti_foto.ClientFoto(transport=httpx.MockTransport(gestore), pausa=0)


def popola(s):
    s.add_all([Squadra(id=1, nome="Inter"), Squadra(id=2, nome="Milan")])
    s.add_all([Giocatore(id=i, nome=f"Nome Cognome{i}") for i in (1, 2, 3, 4)])
    s.flush()
    s.add_all([
        Partita(id=1, data_utc=ADESSO - timedelta(days=10), competizione_id=135, stagione=2026,
                casa_id=1, trasferta_id=2, stato="FT"),
        Partita(id=2, data_utc=ADESSO - timedelta(days=2), competizione_id=135, stagione=2026,
                casa_id=1, trasferta_id=2, stato="FT"),
    ])
    s.flush()
    s.add_all([
        Presenza(partita_id=1, giocatore_id=1, squadra_id=1, minuti=90),
        Presenza(partita_id=2, giocatore_id=2, squadra_id=1, minuti=90),
        Presenza(partita_id=2, giocatore_id=3, squadra_id=2, minuti=90),
    ])
    s.flush()


def test_ordine_per_presenza_piu_recente_e_priorita(sessione):
    popola(sessione)
    # 4 non ha presenze: ultimo; 1 è il più vecchio ma prioritario: primo
    assert caricamento.da_cercare(sessione, ADESSO, 10, priorita_ids=[1]) == [1, 2, 3, 4]
    assert caricamento.da_cercare(sessione, ADESSO, 10) == [2, 3, 1, 4]
    assert caricamento.da_cercare(sessione, ADESSO, 2) == [2, 3]
    assert caricamento.da_cercare(sessione, ADESSO, 0) == []


def test_salva_foto_e_data_del_controllo(sessione):
    popola(sessione)
    richieste = []
    n = caricamento.aggiorna_foto(
        sessione, client_finto({"Nome Cognome2"}, richieste), ADESSO, limite=2
    )
    assert n == 2 and richieste == ["Nome Cognome2", "Nome Cognome3"]
    g2, g3 = sessione.get(Giocatore, 2), sessione.get(Giocatore, 3)
    assert g2.foto_url == URL.format("Nome_Cognome2")
    assert g3.foto_url is None  # controllato, nessuna foto
    assert g2.foto_controllata is not None and g3.foto_controllata is not None
    assert sessione.get(Giocatore, 1).foto_controllata is None


def test_regole_di_ricontrollo(sessione):
    popola(sessione)
    g = {i: sessione.get(Giocatore, i) for i in (1, 2, 3, 4)}
    g[1].foto_controllata = ADESSO - timedelta(days=10)  # senza foto, recente: no
    g[2].foto_controllata = ADESSO - timedelta(days=31)  # senza foto, vecchio: sì
    g[3].foto_controllata, g[3].foto_url = ADESSO - timedelta(days=60), URL.format("a")  # no
    g[4].foto_controllata, g[4].foto_url = ADESSO - timedelta(days=91), URL.format("b")  # sì
    sessione.flush()
    assert set(caricamento.da_cercare(sessione, ADESSO, 10)) == {2, 4}


def test_ricerca_senza_esito_non_cancella_la_foto_vecchia(sessione):
    popola(sessione)
    g = sessione.get(Giocatore, 1)
    g.foto_url, g.foto_controllata = URL.format("vecchia"), ADESSO - timedelta(days=100)
    sessione.flush()
    caricamento.aggiorna_foto(sessione, client_finto(set()), ADESSO, solo_ids=[1])
    assert g.foto_url == URL.format("vecchia") and g.foto_controllata == ADESSO


def test_429_ferma_la_corsa_e_tiene_il_fatto(sessione):
    popola(sessione)
    chiamate = []

    def gestore(richiesta):
        chiamate.append(1)
        if len(chiamate) == 2:
            return httpx.Response(429)
        return httpx.Response(200, json={"player": None})
    client = fonti_foto.ClientFoto(transport=httpx.MockTransport(gestore), pausa=0)
    n = caricamento.aggiorna_foto(sessione, client, ADESSO, limite=4)
    assert n == 1 and len(chiamate) == 2
    assert sessione.get(Giocatore, 2).foto_controllata is not None
    assert sessione.get(Giocatore, 3).foto_controllata is None  # da rifare la prossima volta


def test_giocatori_delle_prossime_partite(sessione):
    popola(sessione)
    sessione.add(Partita(id=3, data_utc=ADESSO + timedelta(days=1), competizione_id=135,
                         stagione=2026, casa_id=1, trasferta_id=2, stato="NS"))
    sessione.add(Partita(id=4, data_utc=ADESSO + timedelta(days=5), competizione_id=135,
                         stagione=2026, casa_id=1, trasferta_id=2, stato="NS"))
    sessione.flush()
    sessione.add_all([
        Formazione(partita_id=3, squadra_id=1, giocatore_id=4, tipo="probabile"),
        Formazione(partita_id=4, squadra_id=1, giocatore_id=1, tipo="probabile"),
    ])
    sessione.flush()
    assert caricamento.giocatori_prossime_partite(sessione, ADESSO) == [4]


def test_passo_dei_job_non_solleva_mai(sessione, monkeypatch):
    popola(sessione)
    monkeypatch.setattr(
        fonti_foto, "crea_client", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert caricamento.aggiorna_foto_senza_errori(sessione, ADESSO, 5) == 0


def test_passo_dei_job_con_rete_finta_503(sessione):
    popola(sessione)  # la fixture di conftest risponde 503: controllati, nessuna foto
    assert caricamento.aggiorna_foto_senza_errori(sessione, ADESSO, 5) == 4
    assert sessione.get(Giocatore, 1).foto_url is None
