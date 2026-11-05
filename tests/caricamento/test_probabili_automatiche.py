from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ammonizioni.caricamento import formazioni
from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra
from ammonizioni.motore.dati import _titolari

BASE = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
OGGI = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)

# 4-4-2: portiere 1, difensori 2-5, centrocampisti 6-9, attaccanti 10-11
XI_442 = [(1, "G", "1:1")] + [
    (2 + i, "D", f"2:{i + 1}") for i in range(4)
] + [(6 + i, "M", f"3:{i + 1}") for i in range(4)] + [(10, "F", "5:1"), (11, "F", "5:2")]
# 3-5-2: portiere 1, difensori 2-4, centrocampisti 6-9 + 12, attaccanti 10-11
XI_352 = [(1, "G", "1:1")] + [
    (2 + i, "D", f"2:{i + 1}") for i in range(3)
] + [(6 + i, "M", f"3:{i + 1}") for i in range(4)] + [(12, "M", "3:5"), (10, "F", "5:1"), (11, "F", "5:2")]


def prepara(s):
    s.add_all([Squadra(id=1, nome="Casa"), Squadra(id=2, nome="Altri")])
    ruoli = {1: "G", 20: "D", 21: "D", 22: "D", 23: "M"}
    for i in range(1, 30):
        s.add(Giocatore(id=i, nome=f"G{i}", ruolo=ruoli.get(i) or ("D" if i < 6 else "M" if i < 10 else "F")))
    s.flush()


def gioca(s, partita_id, giorni, xi, *, competizione=135, stagione=2026, extra=(), squadra=1):
    """Una partita passata della squadra con l'XI dato; `extra`: (giocatore, titolare, gialli, rossi)."""
    s.add(
        Partita(
            id=partita_id, data_utc=BASE + timedelta(days=giorni), competizione_id=competizione,
            stagione=stagione, casa_id=squadra, trasferta_id=2 if squadra == 1 else 1, stato="FT",
            statistiche_scaricate=True,
        )
    )
    s.flush()
    for gid, ruolo, griglia in xi:
        s.add(Presenza(partita_id=partita_id, giocatore_id=gid, squadra_id=squadra, titolare=True,
                       ruolo=ruolo, griglia=griglia, minuti=90))
    for gid, titolare, gialli, rossi in extra:
        s.add(Presenza(partita_id=partita_id, giocatore_id=gid, squadra_id=squadra,
                       titolare=titolare, ruolo="D", griglia=None, minuti=20 if not titolare else 90,
                       gialli=gialli, rossi=rossi))
    s.flush()


def ids(xi):
    return sorted(t.giocatore_id for t in xi)


def test_senza_storico_di_campionato_lista_vuota(sessione):
    prepara(sessione)
    assert formazioni.probabili_automatiche(sessione, 1, OGGI) == []
    gioca(sessione, 1, 1, XI_442, competizione=137)  # coppa: non conta
    assert formazioni.probabili_automatiche(sessione, 1, OGGI) == []


def test_modulo_piu_usato_e_griglia_sintetica(sessione):
    prepara(sessione)
    for n, xi in enumerate([XI_442, XI_352, XI_442, XI_352, XI_352]):
        gioca(sessione, n + 1, n + 1, xi)
    xi = formazioni.probabili_automatiche(sessione, 1, OGGI)
    assert len(xi) == 11
    righe = [t.griglia.split(":")[0] for t in xi]
    assert [righe.count(r) for r in "1235"] == [1, 3, 5, 2]  # 3-5-2 (3 partite su 5)
    assert sorted(t.griglia for t in xi) == sorted(g for _, _, g in XI_352)
    assert all(t.squadra_id == 1 for t in xi)
    assert {t.giocatore_id for t in xi} == {g for g, _, _ in XI_352}


def test_a_parita_di_modulo_vince_il_piu_recente(sessione):
    prepara(sessione)
    gioca(sessione, 1, 1, XI_442)
    gioca(sessione, 2, 2, XI_352)
    xi = formazioni.probabili_automatiche(sessione, 1, OGGI)
    assert sorted(t.griglia for t in xi) == sorted(g for _, _, g in XI_352)


def test_solo_le_ultime_cinque_partite(sessione):
    prepara(sessione)
    gioca(sessione, 1, 1, [(20, "D", "2:1") if g == 2 else (g, r, gr) for g, r, gr in XI_442])
    for n in range(2, 7):
        gioca(sessione, n, n, XI_442)
    xi = formazioni.probabili_automatiche(sessione, 1, OGGI)
    assert 20 not in ids(xi)  # la prima partita e' la sesta all'indietro


def test_squalificato_per_rosso_escluso_e_sostituito_dallo_stesso_ruolo(sessione):
    prepara(sessione)
    # il difensore 20 ha giocato al posto del 2 solo in una partita vecchia
    gioca(sessione, 1, 1, [(20, "D", "2:1") if g == 2 else (g, r, gr) for g, r, gr in XI_442])
    for n in range(2, 5):
        gioca(sessione, n, n, XI_442)
    gioca(sessione, 5, 5, XI_442)
    sessione.get(Presenza, (5, 2)).rossi = 1  # rosso nell'ultima partita
    sessione.flush()
    xi = formazioni.probabili_automatiche(sessione, 1, OGGI)
    assert 2 not in ids(xi)
    assert 20 in ids(xi)
    sostituto = next(t for t in xi if t.giocatore_id == 20)
    assert sostituto.ruolo == "D" and sostituto.griglia.startswith("2:")
    assert len(xi) == 11


def test_rosso_non_nell_ultima_partita_non_squalifica(sessione):
    prepara(sessione)
    for n in range(1, 5):
        gioca(sessione, n, n, XI_442)
    sessione.get(Presenza, (1, 2)).rossi = 1  # rosso di quattro partite fa: scontato
    gioca(sessione, 5, 5, XI_442)
    assert 2 in ids(formazioni.probabili_automatiche(sessione, 1, OGGI))


def test_diffida_che_diventa_squalifica_anche_con_gialli_dalla_panchina(sessione):
    """4 gialli in campionato (uno preso entrando dalla panchina) e il quinto nell'ultima
    partita: squalificato. Chi arriva solo a 4 e' diffidato, ma gioca."""
    prepara(sessione)
    for n in range(1, 5):
        gioca(sessione, n, n, XI_442)
    # giocatore 3: tre gialli da titolare + uno da subentrato, poi il quinto nell'ultima
    for n in (1, 2, 3):
        sessione.get(Presenza, (n, 3)).gialli = 1
    gioca(sessione, 6, 0, [(20, "D", "2:1")], extra=[(3, False, 1, 0)])  # panchina, prima delle altre
    sessione.get(Partita, 6).data_utc = BASE - timedelta(days=5)
    gioca(sessione, 5, 5, XI_442)
    sessione.get(Presenza, (5, 3)).gialli = 1
    # giocatore 4: solo tre gialli prima + il quarto nell'ultima (diffidato, non squalificato)
    for n in (1, 2, 3):
        sessione.get(Presenza, (n, 4)).gialli = 1
    sessione.get(Presenza, (5, 4)).gialli = 1
    sessione.flush()
    xi = formazioni.probabili_automatiche(sessione, 1, OGGI)
    assert 3 not in ids(xi)
    assert 4 in ids(xi)


def test_gialli_di_un_altra_stagione_o_coppa_non_contano(sessione):
    prepara(sessione)
    for n in range(1, 5):
        gioca(sessione, n, n, XI_442)
    gioca(sessione, 5, 5, XI_442)
    # quattro gialli ma in coppa e nella stagione precedente
    gioca(sessione, 20, -300, [(20, "D", "2:1")], stagione=2025, extra=[(3, False, 2, 0)])
    gioca(sessione, 21, 0, [(21, "D", "2:1")], competizione=137, extra=[(3, False, 2, 0)])
    sessione.get(Presenza, (5, 3)).gialli = 1
    sessione.flush()
    assert 3 in ids(formazioni.probabili_automatiche(sessione, 1, OGGI))


def test_somma_dei_gialli_decimal_come_postgres():
    """Su Postgres SUM() da' Decimal: le soglie vanno confrontate con interi."""
    class Risultato:
        def __init__(self, righe):
            self.righe = righe

        def all(self):
            return self.righe

    class SessioneDecimal:
        def __init__(self):
            self.risposte = [
                Risultato([(3, Decimal("0"), Decimal("1")), (4, Decimal("0"), Decimal("1"))]),
                Risultato([(3, Decimal("5"), Decimal("1")), (4, Decimal("4"), Decimal("1"))]),
            ]

        def execute(self, _):
            return self.risposte.pop(0)

    sospesi = formazioni._squalificati(
        SessioneDecimal(), 1, (5, 135, 2026, datetime(2026, 11, 1, tzinfo=timezone.utc))
    )
    assert sospesi == {3}


def test_titolari_dell_ultima_ricaduta_senza_storico_di_campionato(sessione):
    """Senza campionato alle spalle resta `ultimo_xi` (anche da coppa)."""
    prepara(sessione)
    gioca(sessione, 1, 1, XI_442, competizione=137)
    sessione.add(
        Partita(id=100, data_utc=OGGI, competizione_id=135, stagione=2026, casa_id=1,
                trasferta_id=2, stato="NS")
    )
    sessione.flush()
    assert ids(_titolari(sessione, sessione.get(Partita, 100), OGGI)) == ids(
        formazioni.ultimo_xi(sessione, 1, OGGI)
    ) != []


def test_titolari_usa_le_probabili_calcolate_senza_ufficiali(sessione):
    prepara(sessione)
    for n in range(1, 6):
        gioca(sessione, n, n, XI_442)
        gioca(sessione, 50 + n, n, XI_442, squadra=2)
    sessione.add(
        Partita(id=100, data_utc=OGGI, competizione_id=135, stagione=2026, casa_id=1,
                trasferta_id=2, stato="NS")
    )
    sessione.flush()
    titolari = _titolari(sessione, sessione.get(Partita, 100), OGGI)
    assert {t.giocatore_id for t in titolari if t.squadra_id == 1} == {g for g, _, _ in XI_442}
