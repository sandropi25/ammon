"""Passo notturno delle biografie: chi si aggiorna, in che ordine, cosa si salva."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from ammonizioni.caricamento import biografie
from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.biografie import Anagrafica, ProfiloWiki
from ammonizioni.fonti.limite import LimiteSuperato

ADESSO = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)


class ClientFinto:
    def __init__(self, anagrafiche=None, profili=None, errori_espn=(), limite_dopo=None, errori_wiki=()):
        self.anagrafiche = anagrafiche or {}
        self.profili = profili or {}
        self.errori_espn = set(errori_espn)
        self.errori_wiki = set(errori_wiki)
        self.limite_dopo = limite_dopo
        self.espn = []
        self.wiki = []

    def anagrafica(self, gid):
        if self.limite_dopo is not None and len(self.espn) >= self.limite_dopo:
            raise LimiteSuperato("finito")
        self.espn.append(gid)
        if gid in self.errori_espn:
            raise ErroreFonte("rete")
        return self.anagrafiche.get(gid)

    def profilo_wikipedia(self, nome, anno=None):
        self.wiki.append((nome, anno))
        if nome in self.errori_wiki:
            raise ErroreFonte("rete")
        return self.profili.get(nome)


def _popola(s):
    s.add_all([Squadra(id=1, nome="Inter"), Squadra(id=2, nome="Real"), Squadra(id=3, nome="Milan")])
    s.add_all([
        Giocatore(id=10, nome="Liga Tanti"), Giocatore(id=11, nome="Serie A Pochi"),
        Giocatore(id=12, nome="Serie A Tanti"), Giocatore(id=13, nome="Panchina Ammonito"),
        Giocatore(id=14, nome="Stagione Scorsa"),
    ])
    s.flush()
    s.add_all([
        Partita(id=1, data_utc=ADESSO - timedelta(days=5), competizione_id=135, stagione=2026,
                casa_id=1, trasferta_id=3, stato="FT"),
        Partita(id=2, data_utc=ADESSO - timedelta(days=5), competizione_id=140, stagione=2026,
                casa_id=2, trasferta_id=2, stato="FT"),
        Partita(id=3, data_utc=ADESSO - timedelta(days=400), competizione_id=135, stagione=2025,
                casa_id=1, trasferta_id=3, stato="FT"),
    ])
    s.flush()
    s.add_all([
        Presenza(partita_id=2, giocatore_id=10, squadra_id=2, minuti=90, gialli=5),
        Presenza(partita_id=1, giocatore_id=11, squadra_id=1, minuti=90, gialli=0),
        Presenza(partita_id=1, giocatore_id=12, squadra_id=1, minuti=90, gialli=2),
        # ammonito dalla panchina senza minuti: conta anche lui
        Presenza(partita_id=1, giocatore_id=13, squadra_id=3, minuti=0, gialli=1),
        Presenza(partita_id=3, giocatore_id=14, squadra_id=1, minuti=90, gialli=3),
    ])
    s.commit()


def test_ordine_serie_a_prima_poi_i_piu_ammoniti(sessione):
    _popola(sessione)
    assert biografie.da_aggiornare(sessione, ADESSO, 10) == [12, 13, 11, 10]
    assert biografie.da_aggiornare(sessione, ADESSO, 2) == [12, 13]
    assert biografie.da_aggiornare(sessione, ADESSO, 0) == []


def test_rinnovo_al_massimo_mensile(sessione):
    _popola(sessione)
    sessione.get(Giocatore, 12).bio_aggiornata = ADESSO - timedelta(days=10)
    sessione.get(Giocatore, 13).bio_aggiornata = ADESSO - timedelta(days=31)
    sessione.commit()
    assert biografie.da_aggiornare(sessione, ADESSO, 10) == [13, 11, 10]


def test_somme_decimal_convertite(sessione, monkeypatch):
    """Su Postgres SUM restituisce Decimal: l'ordinamento e i totali restano interi."""
    _popola(sessione)
    originale = sessione.execute

    class Righe:
        def __init__(self, righe):
            self._righe = righe

        def all(self):
            return [(g, c, Decimal(n) if n is not None else None) for g, c, n in self._righe]

    monkeypatch.setattr(sessione, "execute", lambda *a, **k: Righe(originale(*a, **k).all()))
    assert biografie.da_aggiornare(sessione, ADESSO, 10) == [12, 13, 11, 10]


def test_aggiorna_salva_anagrafica_e_wikipedia(sessione):
    _popola(sessione)
    client = ClientFinto(
        anagrafiche={12: Anagrafica(date(1999, 1, 2), "Italia", 183, "Difensore")},
        profili={"Serie A Tanti": ProfiloWiki("Serie A Tanti", "https://it.wikipedia.org/wiki/X", "Testo.", "it")},
    )
    r = biografie.aggiorna(sessione, client, adesso=ADESSO, quanti=2)
    assert (r.controllati, r.con_anagrafica, r.con_wikipedia, r.completo) == (2, 1, 1, True)
    assert client.wiki == [("Serie A Tanti", 1999), ("Panchina Ammonito", None)]
    g = sessione.get(Giocatore, 12)
    assert (g.data_nascita, g.nazionalita, g.altezza_cm, g.posizione) == (date(1999, 1, 2), "Italia", 183, "Difensore")
    assert (g.wiki_titolo, g.wiki_url, g.wiki_estratto) == ("Serie A Tanti", "https://it.wikipedia.org/wiki/X", "Testo.")
    assert g.bio_aggiornata == ADESSO
    # niente trovato: nessun dato, ma il controllo è segnato (si riprova fra un mese)
    vuoto = sessione.get(Giocatore, 13)
    assert vuoto.wiki_estratto is None and vuoto.data_nascita is None and vuoto.bio_aggiornata == ADESSO
    # la notte dopo non si richiedono di nuovo
    assert biografie.da_aggiornare(sessione, ADESSO + timedelta(days=1), 10) == [11, 10]


def test_voce_dubbia_non_cancella_quella_salvata(sessione):
    _popola(sessione)
    g = sessione.get(Giocatore, 12)
    g.wiki_estratto, g.wiki_url = "Vecchio testo.", "https://it.wikipedia.org/wiki/V"
    g.bio_aggiornata = ADESSO - timedelta(days=40)
    sessione.commit()
    biografie.aggiorna(sessione, ClientFinto(), adesso=ADESSO, quanti=1)
    assert sessione.get(Giocatore, 12).wiki_estratto == "Vecchio testo."


def test_limite_espn_ferma_e_errori_proseguono(sessione):
    _popola(sessione)
    client = ClientFinto(limite_dopo=1, errori_espn={12})
    r = biografie.aggiorna(sessione, client, adesso=ADESSO, quanti=10)
    assert r.completo is False and r.controllati == 1  # 12 con errore ESPN, poi limite finito
    assert sessione.get(Giocatore, 12).bio_aggiornata == ADESSO
    assert sessione.get(Giocatore, 13).bio_aggiornata is None


def test_senza_espn_solo_wikipedia_ed_errore_wikipedia(sessione):
    _popola(sessione)
    client = ClientFinto(errori_wiki={"Serie A Tanti"})
    r = biografie.aggiorna(sessione, client, adesso=ADESSO, quanti=2, usa_espn=False)
    assert client.espn == [] and r.controllati == 2 and r.completo is False


def test_massimo_per_notte_da_ambiente(monkeypatch):
    monkeypatch.delenv("BIO_PER_NOTTE", raising=False)
    assert biografie.massimo_per_notte() == 40
    monkeypatch.setenv("BIO_PER_NOTTE", "5")
    assert biografie.massimo_per_notte() == 5
    monkeypatch.setenv("BIO_PER_NOTTE", "abc")
    assert biografie.massimo_per_notte() == 40
