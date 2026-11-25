from datetime import datetime, timezone

from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Squadra
from ammonizioni.marcatori.dati import rosa_partita

QUANDO = datetime(2026, 11, 28, 14, 0, tzinfo=timezone.utc)


def prepara(s):
    s.add_all([Squadra(id=1, nome="Casa"), Squadra(id=2, nome="Ospiti")])
    for i in range(1, 9):
        s.add(Giocatore(id=i, nome=f"G{i}", ruolo="F"))
    s.add(Partita(id=10, data_utc=QUANDO, competizione_id=135, stagione=2026, casa_id=1,
                  trasferta_id=2, stato="NS"))
    s.flush()


def formazione(s, squadra, giocatore, tipo):
    s.add(Formazione(partita_id=10, squadra_id=squadra, giocatore_id=giocatore, tipo=tipo))
    s.flush()


def test_ufficiale_di_una_squadra_e_probabile_dell_altra(sessione):
    """ESPN pubblica le ufficiali una squadra alla volta: l'altra resta con la probabile."""
    prepara(sessione)
    formazione(sessione, 1, 1, "probabile")
    formazione(sessione, 1, 2, "ufficiale")
    formazione(sessione, 1, 3, "panchina")
    formazione(sessione, 2, 5, "probabile")
    rosa, tipo = rosa_partita(sessione, sessione.get(Partita, 10))
    assert tipo == "miste"
    assert {(g.giocatore_id, g.titolare) for g in rosa} == {(2, True), (3, False), (5, True)}


def test_ufficiali_di_entrambe(sessione):
    prepara(sessione)
    formazione(sessione, 1, 2, "ufficiale")
    formazione(sessione, 2, 6, "ufficiale")
    formazione(sessione, 2, 7, "panchina")
    formazione(sessione, 2, 5, "probabile")
    rosa, tipo = rosa_partita(sessione, sessione.get(Partita, 10))
    assert tipo == "ufficiali"
    assert {(g.giocatore_id, g.titolare) for g in rosa} == {(2, True), (6, True), (7, False)}


def test_solo_probabili(sessione):
    prepara(sessione)
    formazione(sessione, 1, 1, "probabile")
    formazione(sessione, 2, 5, "probabile")
    rosa, tipo = rosa_partita(sessione, sessione.get(Partita, 10))
    assert tipo == "probabili" and {g.giocatore_id for g in rosa} == {1, 5}


def test_pronostico_segnala_il_favorito_in_panchina(sessione, monkeypatch):
    from ammonizioni.marcatori import pronostici
    from ammonizioni.marcatori.modello import Giocante, Parametri, Storico

    prepara(sessione)
    formazione(sessione, 1, 2, "ufficiale")
    formazione(sessione, 1, 1, "panchina")  # il bomber parte dalla panchina
    formazione(sessione, 2, 5, "probabile")
    monkeypatch.setattr(pronostici, "stimate_squadra",
                        lambda s, sq, quando: [Giocante(1, 1, True, "F"), Giocante(2, 1, True, "F")])
    storico = Storico(Parametri(a=2.0))  # tutti molto probabili: il bomber supera la soglia
    [pr] = pronostici.pronostica(sessione, [sessione.get(Partita, 10)], storico)
    assert pr.formazioni == "miste" and pr.tipi_squadra == ("ufficiale", "probabile")
    assert [(g, panca) for g, _, panca in pr.esclusi] == [(1, True)]
