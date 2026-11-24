from datetime import datetime, timedelta, timezone

from ammonizioni import resoconto
from ammonizioni.db import repo
from ammonizioni.db.modelli import Arbitro, Giocatore, Partita, Presenza, Squadra

INIZIO = datetime(2026, 11, 21, 14, 0, tzinfo=timezone.utc)
DOPO = INIZIO + timedelta(days=3)


def squadre(s):
    s.add_all([Squadra(id=i, nome=f"S{i}") for i in range(1, 5)])
    s.add_all([Giocatore(id=i, nome=f"G{i}", ruolo="M") for i in range(1, 9)])
    s.add(Arbitro(id=1, nome_normalizzato="mario rossi", nome_visualizzato="Mario Rossi"))
    s.flush()


def partita(s, id, data=INIZIO, comp=135, giornata=12, stato="FT", stats=True, casa=1, trasf=2,
            formazioni="probabili"):
    p = Partita(
        id=id, data_utc=data, competizione_id=comp, stagione=2026, giornata=giornata,
        casa_id=casa, trasferta_id=trasf, stato=stato, statistiche_scaricate=stats,
        gol_casa=2, gol_trasferta=1, gialli_totali=2, rossi_totali=0, falli_totali=20,
        arbitro_id=1, stato_formazioni=formazioni,
    )
    s.add(p)
    s.flush()
    return p


def presenza(s, partita_id, gid, squadra, gialli=0, minuto=None, falli=0, rossi=0):
    s.add(Presenza(partita_id=partita_id, giocatore_id=gid, squadra_id=squadra, titolare=True,
                   gialli=gialli, rossi=rossi, minuto_giallo=minuto, falli_commessi=falli))
    s.flush()


def test_cernita_fissata_prima_del_via_e_rifatta_con_le_ufficiali(sessione):
    squadre(sessione)
    p = partita(sessione, 10, stato="NS", stats=False)
    prima = INIZIO - timedelta(minutes=60)
    assert resoconto.salva_cernita(sessione, p, prima, lambda s, i: [3, 1, 2])
    # ancora probabili: non si rifà
    assert not resoconto.salva_cernita(sessione, p, prima, lambda s, i: [9])
    p.stato_formazioni = "ufficiali"
    assert resoconto.salva_cernita(sessione, p, prima, lambda s, i: [1, 2, 3])
    salvata = repo.leggi_impostazione(sessione, "cernita_10")
    assert salvata["ids"] == [1, 2, 3] and salvata["formazioni"] == "ufficiali"
    # ufficiali gia' salvate, o partita iniziata: non cambia piu'
    assert not resoconto.salva_cernita(sessione, p, prima, lambda s, i: [9])
    p2 = partita(sessione, 11, stato="NS", stats=False)
    assert not resoconto.salva_cernita(sessione, p2, INIZIO, lambda s, i: [9])


def test_resoconto_della_giornata_quando_finisce_l_ultima_partita(sessione):
    squadre(sessione)
    partita(sessione, 20)
    ultima = partita(sessione, 21, data=INIZIO + timedelta(days=1), casa=3, trasf=4,
                     stato="NS", stats=False)
    repo.scrivi_impostazione(sessione, "cernita_20", {"ids": [2, 1, 3, 4], "formazioni": "ufficiali"})
    presenza(sessione, 20, 1, 1, gialli=1, minuto=55, falli=2)
    presenza(sessione, 20, 3, 2, gialli=1, minuto=12, falli=1)
    presenza(sessione, 20, 4, 2, falli=4)  # graziato
    assert resoconto.chiudi_giornate(sessione, DOPO, set()) == 0  # manca ancora la 21
    ultima.stato, ultima.statistiche_scaricate = "FT", True
    presenza(sessione, 21, 5, 3, gialli=1, minuto=30)
    assert resoconto.chiudi_giornate(sessione, DOPO, set()) == 1
    assert resoconto.chiudi_giornate(sessione, DOPO, set()) == 0  # una volta sola
    r = repo.leggi_impostazione(sessione, "resoconto_135_2026_12")
    prima = r["partite"][0]
    assert [(a["nome"], a["minuto"], a["posizione"]) for a in prima["ammoniti"]] == [
        ("G3", 12, 3), ("G1", 55, 2),
    ]
    assert prima["primi_ammoniti"] == 2 and prima["arbitro"] == "Mario Rossi"
    assert [g["nome"] for g in prima["graziati"]] == ["G4"]
    assert r["partite"][1]["primi_ammoniti"] is None  # senza cernita salvata
    assert r["partite_con_cernita"] == 1 and r["partite_primi_ammoniti"] == 1
    precisione = repo.leggi_impostazione(sessione, "precisione_cernita")["135"]
    assert precisione["partite"] == 2 and precisione["partite_primi_ammoniti"] == 1


def test_giornata_mancante_presa_dalla_partita_vicina_e_rinviate_escluse(sessione):
    squadre(sessione)
    partita(sessione, 30, comp=61, giornata=12)
    partita(sessione, 31, comp=61, giornata=None, data=INIZIO + timedelta(days=1), casa=3, trasf=4,
            stato="NS", stats=False)
    partita(sessione, 32, comp=61, giornata=12, stato="PST", stats=False, casa=3, trasf=1)
    assert resoconto.giornate_concluse(sessione, DOPO, set()) == []  # la 31 e' della 12
    assert [g[:3] for g in resoconto.giornate_concluse(sessione, DOPO, {31})] == []  # non finita
    sessione.get(Partita, 31).stato = "FT"
    pronte = resoconto.giornate_concluse(sessione, DOPO, {31})  # chiusa senza statistiche
    assert [(g[:3], [p.id for p in g[3]]) for g in pronte] == [((61, 2026, 12), [30, 31])]


def test_giornate_vecchie_restano_fuori(sessione):
    squadre(sessione)
    partita(sessione, 40)
    assert resoconto.giornate_concluse(sessione, INIZIO + timedelta(days=11), set()) == []
