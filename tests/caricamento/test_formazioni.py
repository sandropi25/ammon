from datetime import datetime, timezone

from sqlalchemy import select

from ammonizioni.caricamento import formazioni
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra

INIZIO = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
FUTURO = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)


def prepara(s):
    s.add_all([Squadra(id=1, nome="Casa"), Squadra(id=2, nome="Trasferta")])
    s.add_all(
        [Giocatore(id=i, nome=f"G{i}", ruolo="D" if i % 2 else "F") for i in range(1, 8)]
    )
    s.flush()


def aggiungi_partita(s, id, data, competizione=135, stato="FT"):
    s.add(
        Partita(
            id=id, data_utc=data, competizione_id=competizione, stagione=2026,
            casa_id=1, trasferta_id=2, stato=stato,
        )
    )
    s.flush()


def presenza(s, partita_id, giocatore_id, titolare=True, squadra_id=1):
    s.add(
        Presenza(
            partita_id=partita_id, giocatore_id=giocatore_id, squadra_id=squadra_id,
            titolare=titolare, ruolo="D", griglia="2:1",
        )
    )
    s.flush()


def ids(tipo, s, partita_id=100, squadra_id=1):
    return sorted(
        s.scalars(
            select(Formazione.giocatore_id).where(
                Formazione.partita_id == partita_id,
                Formazione.squadra_id == squadra_id,
                Formazione.tipo == tipo,
            )
        )
    )


def test_ultimo_xi_anche_da_coppa(sessione):
    prepara(sessione)
    aggiungi_partita(sessione, 1, datetime(2026, 9, 20, tzinfo=timezone.utc))
    aggiungi_partita(sessione, 2, datetime(2026, 9, 27, tzinfo=timezone.utc), competizione=137)
    for g in (1, 2):
        presenza(sessione, 1, g)
    for g in (3, 4):
        presenza(sessione, 2, g)
    presenza(sessione, 2, 5, titolare=False)  # panchina: esclusa
    xi = formazioni.ultimo_xi(sessione, 1, INIZIO)
    assert [t.giocatore_id for t in xi] == [3, 4]
    assert all(t.squadra_id == 1 and t.griglia == "2:1" and t.ruolo == "D" for t in xi)
    assert xi[0].nome == "G3"


def test_ultimo_xi_rispetta_prima_di_e_vuoto(sessione):
    prepara(sessione)
    assert formazioni.ultimo_xi(sessione, 1, INIZIO) == []
    aggiungi_partita(sessione, 1, datetime(2026, 9, 20, tzinfo=timezone.utc))
    presenza(sessione, 1, 1)
    assert formazioni.ultimo_xi(sessione, 1, datetime(2026, 9, 20, tzinfo=timezone.utc)) == []


def test_salva_probabili_sostituisce_le_precedenti_e_lascia_le_ufficiali(sessione):
    prepara(sessione)
    aggiungi_partita(sessione, 100, FUTURO, stato="NS")
    sessione.add(Formazione(partita_id=100, squadra_id=1, giocatore_id=7, tipo="ufficiale"))
    sessione.flush()
    formazioni.salva_probabili(sessione, 100, {1: [1, 2, 3], 2: [4, 5]})
    formazioni.salva_probabili(sessione, 100, {1: [2, 3, 6], 2: [4, 5]})
    assert ids("probabile", sessione) == [2, 3, 6]
    assert ids("probabile", sessione, squadra_id=2) == [4, 5]
    assert ids("ufficiale", sessione) == [7]


def test_riepilogo_cambi(sessione):
    prepara(sessione)
    aggiungi_partita(sessione, 100, FUTURO, stato="NS")
    formazioni.salva_probabili(sessione, 100, {1: [1, 2, 3], 2: [4, 5]})
    for g in (2, 3, 6):
        sessione.add(Formazione(partita_id=100, squadra_id=1, giocatore_id=g, tipo="ufficiale"))
    for g in (4, 5):
        sessione.add(Formazione(partita_id=100, squadra_id=2, giocatore_id=g, tipo="ufficiale"))
    sessione.flush()
    assert formazioni.riepilogo_cambi(sessione, 100) == {1: ([6], [1]), 2: ([], [])}


def test_riepilogo_cambi_vuoto_se_manca_un_tipo(sessione):
    prepara(sessione)
    aggiungi_partita(sessione, 100, FUTURO, stato="NS")
    assert formazioni.riepilogo_cambi(sessione, 100) == {}
    formazioni.salva_probabili(sessione, 100, {1: [1, 2]})
    assert formazioni.riepilogo_cambi(sessione, 100) == {}
    sessione.add(Formazione(partita_id=100, squadra_id=1, giocatore_id=3, tipo="ufficiale"))
    sessione.flush()
    assert formazioni.riepilogo_cambi(sessione, 100) == {1: ([3], [1, 2])}
