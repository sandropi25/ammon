"""Logica della pagina Cerca: ricerca senza accenti, scheda del giocatore, partite della squadra."""
from datetime import datetime, timedelta, timezone

from ayuda_app import sessione_db, url_db  # noqa: F401  (fixture)
from db_prova import CASA, DATA_FUTURA, PARTITA_FUTURA, TRASF, popola

import componenti_cerca as cerca

from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra

ADESSO = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
CALHA = 500


def _prepara(s):
    popola(s)
    s.add(Giocatore(id=CALHA, nome="Hakan Çalhanoğlu", ruolo="M"))
    s.flush()
    # panchina: subentrato 0 minuti ma ammonito (partita 1), poi 2 presenze vere
    s.add(Presenza(partita_id=1, giocatore_id=CALHA, squadra_id=CASA, minuti=0, gialli=1,
                   falli_commessi=1))
    s.add(Presenza(partita_id=2, giocatore_id=CALHA, squadra_id=CASA, minuti=90, gialli=1,
                   rossi=0, falli_commessi=3, falli_subiti=2))
    s.add(Presenza(partita_id=3, giocatore_id=CALHA, squadra_id=CASA, minuti=45, gialli=0,
                   falli_commessi=1, falli_subiti=1))
    s.flush()


# ---------------------------------------------------------------- ricerca

def test_normalizza_toglie_accenti_e_maiuscole():
    assert cerca.normalizza("Çalhanoğlu") == "calhanoglu"
    assert cerca.normalizza("  Ørsted  Łukasz ") == "orsted lukasz"


def test_cerca_calhanoglu_trova_calhanoglu(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        indice = cerca.carica_indice(s)
    giocatori, _ = cerca.cerca_giocatori(indice, "calhanoglu")
    assert [g.nome for g in giocatori] == ["Hakan Çalhanoğlu"]
    assert giocatori[0].squadra == "Casa FC"
    assert [g.nome for g in cerca.cerca_giocatori(indice, "ÇALHAN")[0]] == ["Hakan Çalhanoğlu"]
    assert cerca.cerca_giocatori(indice, "hakan calha")[0][0].id == CALHA


def test_cerca_gruppi_separati_e_massimo_20(sessione_db):
    with sessione_db() as s:
        popola(s)
        for i in range(30):
            s.add(Giocatore(id=900 + i, nome=f"Casa Giocatore {i:02d}", ruolo="D"))
        s.flush()
        indice = cerca.carica_indice(s)
    giocatori, _ = cerca.cerca_giocatori(indice, "casa")
    assert len(giocatori) == 20
    squadre, _ = cerca.cerca_squadre(indice, "casa", (135,))
    assert [q.nome for q in squadre] == ["Casa FC"]
    assert cerca.cerca_giocatori(indice, "c") == ([], 0)  # troppo corta


def test_squadre_filtrate_per_campionato(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.add(Squadra(id=501, nome="Real Liga"))
        s.add(Squadra(id=502, nome="Real Senza Partite"))
        s.flush()
        s.add(Partita(id=900, data_utc=ADESSO + timedelta(days=3), competizione_id=140,
                      stagione=2026, casa_id=501, trasferta_id=502, stato="NS"))
        s.flush()
        indice = cerca.carica_indice(s)
    serie_a, nascoste = cerca.cerca_squadre(indice, "real", (135,))
    assert serie_a == [] and nascoste == 2
    liga, _ = cerca.cerca_squadre(indice, "real", (140,))
    assert [q.nome for q in liga] == ["Real Liga", "Real Senza Partite"]
    tutti, nascoste = cerca.cerca_squadre(indice, "real", (135, 140), tutti=True)
    assert len(tutti) == 2 and nascoste == 0


# ---------------------------------------------------------------- scheda del giocatore

def test_scheda_conta_il_giallo_dalla_panchina(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        scheda = cerca.scheda_giocatore(s, CALHA, ADESSO)
    assert scheda.nome == "Hakan Çalhanoğlu" and scheda.squadra == "Casa FC"
    (riga,) = scheda.stagioni
    assert (riga.stagione, riga.competizione) == (2026, "Serie A")
    assert riga.presenze == 2  # la panchina a 0 minuti non e' una presenza
    assert riga.minuti == 135
    assert riga.gialli == 2  # ma il suo giallo conta
    assert riga.falli_commessi == 5 and riga.falli_subiti == 3
    assert round(riga.gialli90, 2) == 1.33  # 2 gialli su 135 minuti
    assert all(isinstance(v, (int, float)) for v in (riga.presenze, riga.minuti, riga.gialli))


def test_scheda_diffidato_con_la_soglia_del_campionato(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        s.add(Presenza(partita_id=4, giocatore_id=CALHA, squadra_id=CASA, minuti=90, gialli=1))
        s.add(Presenza(partita_id=5, giocatore_id=CALHA, squadra_id=CASA, minuti=90, gialli=1))
        s.flush()
        scheda = cerca.scheda_giocatore(s, CALHA, ADESSO)
    assert scheda.gialli_campionato == 4 and scheda.diffidato is True


def test_scheda_non_diffidato(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        assert cerca.scheda_giocatore(s, CALHA, ADESSO).diffidato is False


def test_scheda_ultime_5_partite_con_avversario(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        for i in (4, 5, 6):
            s.add(Presenza(partita_id=i, giocatore_id=CALHA, squadra_id=CASA, minuti=60,
                           falli_commessi=2))
        s.flush()
        scheda = cerca.scheda_giocatore(s, CALHA, ADESSO)
    assert len(scheda.ultime) == 5
    assert [u.data_ordinabile for u in scheda.ultime] == sorted(
        (u.data_ordinabile for u in scheda.ultime), reverse=True
    )
    assert scheda.ultime[0].avversario == "Trasferta FC"
    # la partita 1 (panchina, ammonito) e' la sesta: fuori dalle ultime 5
    assert scheda.ultime[-1].minuti == 90


def test_scheda_prossima_partita_con_probabilita_arbitro_e_storia(sessione_db):
    with sessione_db() as s:
        popola(s)
        scheda = cerca.scheda_giocatore(s, 12, ADESSO)  # Terzino Casa, titolare
    p = scheda.prossima
    assert p is not None and p.partita_id == PARTITA_FUTURA
    assert p.avversario == "Trasferta FC" and p.in_casa is True
    assert p.quando == "domenica 8 novembre 2026 · 19:00"  # 18:00 UTC, ora solare
    assert p.candidato is not None and 0 < p.candidato.probabilita < 1
    assert p.arbitro == "Rossi"
    presenze, gialli = p.con_arbitro
    assert presenze == 6 and isinstance(gialli, int)
    assert "Contro Trasferta FC: 6 partite" in p.storia
    assert p.derby is not None and "derby" in p.derby.lower()


def test_scheda_senza_prossima_partita(sessione_db):
    with sessione_db() as s:
        _prepara(s)
        s.delete(s.get(Partita, PARTITA_FUTURA))
        s.flush()
        scheda = cerca.scheda_giocatore(s, CALHA, ADESSO)
    assert scheda.prossima is None


def test_scheda_giocatore_inesistente(sessione_db):
    with sessione_db() as s:
        popola(s)
        assert cerca.scheda_giocatore(s, 99999, ADESSO) is None


# ---------------------------------------------------------------- squadra

def test_partite_squadra_in_ordine_entro_30_giorni(sessione_db):
    with sessione_db() as s:
        popola(s)
        for pid, giorni in ((300, 20), (301, 2), (302, 45)):
            s.add(Partita(id=pid, data_utc=ADESSO + timedelta(days=giorni), competizione_id=135,
                          stagione=2026, giornata=9, casa_id=TRASF, trasferta_id=CASA, stato="NS"))
        s.flush()
        righe = cerca.partite_squadra(s, CASA, ADESSO)
    assert [r.id for r in righe] == [301, PARTITA_FUTURA, 300]  # la 302 e' oltre i 30 giorni
    assert [r.id for r in righe] == sorted((r.id for r in righe), key=lambda i: next(
        r.data_utc for r in righe if r.id == i))


def test_data_estesa_in_italiano():
    # 19:45 UTC di domenica 8 novembre 2026 = 20:45 a Roma (ora solare)
    assert cerca.data_estesa(datetime(2026, 11, 8, 19, 45, tzinfo=timezone.utc)) == (
        "domenica 8 novembre 2026 · 20:45"
    )
    # in estate +2 ore: 18:30 UTC del 1 agosto 2026 (sabato) = 20:30
    assert cerca.data_estesa(datetime(2026, 8, 1, 18, 30, tzinfo=timezone.utc)) == (
        "sabato 1 agosto 2026 · 20:30"
    )
