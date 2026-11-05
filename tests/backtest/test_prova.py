from datetime import datetime, timedelta, timezone

import pytest

import importlib.util
from pathlib import Path

from ammonizioni.backtest.prova import Copertura, RisultatoProva, copertura, prova_stagione
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Arbitro, Giocatore, Partita, Presenza, Squadra

SERIE_A = 135
LIGA = 140
COPPA_ITALIA = 137
STAGIONE = 2025
INIZIO = datetime(2025, 9, 1, 18, 0, tzinfo=timezone.utc)

# squadra -> [(id, ruolo)]
ROSE = {
    1: [(11, "G"), (12, "D"), (13, "M"), (14, "F")],
    2: [(21, "G"), (22, "D"), (23, "M"), (24, "F")],
}


def anagrafica(s) -> None:
    s.add_all([Squadra(id=1, nome="Casa FC"), Squadra(id=2, nome="Trasferta FC")])
    for lista in ROSE.values():
        for gid, ruolo in lista:
            s.add(Giocatore(id=gid, nome=f"Giocatore {gid}", ruolo=ruolo))
    s.flush()


def aggiungi_partita(
    s,
    pid: int,
    giorni: int,
    *,
    gialli: dict[int, int] | None = None,
    minuti: dict[int, int] | None = None,
    competizione: int = SERIE_A,
    statistiche: bool = True,
    squadre: tuple[int, ...] = (1, 2),
) -> None:
    """Partita `giorni` dopo INIZIO con i titolari di `squadre`; `gialli`/`minuti` per giocatore."""
    gialli = gialli or {}
    minuti = minuti or {}
    s.add(
        Partita(
            id=pid, data_utc=INIZIO + timedelta(days=giorni), competizione_id=competizione,
            stagione=STAGIONE, giornata=pid, casa_id=1, trasferta_id=2, gol_casa=1,
            gol_trasferta=1, stato="FT", statistiche_scaricate=statistiche,
        )
    )
    s.flush()
    for sq in squadre:
        for gid, ruolo in ROSE[sq]:
            s.add(
                Presenza(
                    partita_id=pid, giocatore_id=gid, squadra_id=sq, titolare=True,
                    # griglia None come in produzione per le partite passate
                    # (/fixtures/players non la fornisce): duello neutro
                    ruolo=ruolo, griglia=None, minuti=minuti.get(gid, 90),
                    gialli=gialli.get(gid, 0), falli_commessi=2, falli_subiti=1, voto=6.0,
                )
            )
    s.flush()


def test_successo_se_uno_dei_primi_3_ammonito(sessione):
    anagrafica(sessione)
    # il giocatore 12 ha 3 gialli nelle ultime partite (Coppa Italia: contano per il modello
    # e non sono partite da valutare)
    for i, pid in enumerate((1, 2, 3)):
        aggiungi_partita(
            sessione, pid, i, gialli={12: 1}, competizione=COPPA_ITALIA, statistiche=False
        )
    aggiungi_partita(sessione, 10, 30, gialli={12: 1})

    r = prova_stagione(sessione, STAGIONE, k=3)

    assert r.partite == 1
    assert r.successi_modello == 1
    assert r.tasso_modello == 1.0


def test_nessun_dato_futuro(sessione):
    anagrafica(sessione)
    aggiungi_partita(sessione, 10, 30, gialli={14: 1})
    # dopo la partita il 14 prende molti gialli in Serie A: non deve influenzare la classifica
    for i, pid in enumerate((20, 21, 22, 23)):
        aggiungi_partita(sessione, pid, 40 + i, gialli={14: 1}, statistiche=False)

    r = prova_stagione(sessione, STAGIONE, k=1)

    assert r.partite == 1
    assert r.successi_modello == 0
    assert r.successi_base == 0


@pytest.mark.parametrize(
    "ammonito, atteso",
    [(22, 1), (13, 0)],
    ids=["scelto_per_gialli_e_minuti", "scartato_a_parita_di_gialli_meno_minuti"],
)
def test_scelta_semplice_piu_gialli_in_stagione(sessione, ammonito, atteso):
    anagrafica(sessione)
    # storico Serie A prima della partita: 12 -> 2 gialli, 13 e 22 -> 1 giallo ciascuno,
    # ma il 22 ha giocato di piu' (180' contro 90'): con k=2 la scelta e' {12, 22}
    aggiungi_partita(
        sessione, 1, 0, gialli={12: 1, 13: 1}, minuti={13: 45, 22: 90}, statistiche=False
    )
    aggiungi_partita(
        sessione, 2, 7, gialli={12: 1, 22: 1}, minuti={13: 45, 22: 90}, statistiche=False
    )
    aggiungi_partita(sessione, 10, 30, gialli={ammonito: 1})

    r = prova_stagione(sessione, STAGIONE, k=2)

    assert r.partite == 1
    assert r.successi_base == atteso
    assert r.tasso_base == float(atteso)


def test_nessuna_partita(sessione):
    anagrafica(sessione)

    r = prova_stagione(sessione, STAGIONE)

    assert r == RisultatoProva(0, 0, 0, 0.0, 0.0)


def test_salta_partite_con_meno_di_2_titolari_per_squadra(sessione):
    anagrafica(sessione)
    aggiungi_partita(sessione, 10, 30, gialli={12: 1}, squadre=(1,))  # manca la trasferta
    aggiungi_partita(sessione, 11, 37, gialli={12: 1})

    r = prova_stagione(sessione, STAGIONE)

    assert r.partite == 1


def test_avanzamento_chiamato_dopo_ogni_partita(sessione):
    anagrafica(sessione)
    aggiungi_partita(sessione, 10, 30)
    aggiungi_partita(sessione, 11, 37)
    chiamate: list[tuple[int, int]] = []

    prova_stagione(sessione, STAGIONE, avanzamento=lambda fatte, totale: chiamate.append((fatte, totale)))

    assert chiamate == [(1, 2), (2, 2)]


def test_liga_nello_stesso_db_non_cambia_la_serie_a(sessione):
    anagrafica(sessione)
    # in Liga il 14 prende 2 gialli: se contassero per la Serie A, la scelta semplice
    # (k=1) sceglierebbe lui invece del 12
    aggiungi_partita(sessione, 1, 0, gialli={12: 1}, statistiche=False)
    aggiungi_partita(sessione, 2, 1, gialli={14: 1}, competizione=LIGA, statistiche=False)
    aggiungi_partita(sessione, 3, 2, gialli={14: 1}, competizione=LIGA, statistiche=False)
    aggiungi_partita(sessione, 4, 3, gialli={14: 1}, competizione=LIGA)  # Liga da valutare
    aggiungi_partita(sessione, 10, 30, gialli={12: 1})

    r = prova_stagione(sessione, STAGIONE, k=1)

    assert r.partite == 1
    assert r.successi_base == 1


def test_competizione_140_conta_solo_la_liga(sessione):
    anagrafica(sessione)
    aggiungi_partita(sessione, 1, 0, gialli={12: 1}, statistiche=False)  # Serie A
    aggiungi_partita(sessione, 2, 1, gialli={14: 1}, competizione=LIGA, statistiche=False)
    aggiungi_partita(sessione, 3, 2, gialli={14: 1}, competizione=LIGA, statistiche=False)
    aggiungi_partita(sessione, 10, 30, gialli={14: 1}, competizione=LIGA)
    aggiungi_partita(sessione, 11, 31, gialli={12: 1})  # Serie A: non conta

    r = prova_stagione(sessione, STAGIONE, k=1, competizione_id=LIGA)

    assert r.partite == 1
    assert r.successi_base == 1  # il 14 ha 2 gialli in Liga


def test_copertura_conta_arbitro_e_griglia(sessione):
    anagrafica(sessione)
    sessione.add(Arbitro(id=1, nome_normalizzato="rossi", nome_visualizzato="Rossi"))
    sessione.flush()
    aggiungi_partita(sessione, 1, 0)  # nessun arbitro, nessuna griglia
    aggiungi_partita(sessione, 2, 7)
    aggiungi_partita(sessione, 3, 14)
    aggiungi_partita(sessione, 4, 21, statistiche=False)  # non finita con statistiche: fuori
    aggiungi_partita(sessione, 5, 28, competizione=LIGA)  # altro campionato: fuori
    sessione.get(Partita, 2).arbitro_id = 1
    sessione.get(Partita, 3).arbitro_id = 1
    sessione.get(Presenza, (3, 12)).griglia = "3:2"
    sessione.get(Presenza, (4, 12)).griglia = "3:2"
    sessione.flush()

    assert copertura(sessione, STAGIONE, SERIE_A) == Copertura(3, 2, 1)
    assert copertura(sessione, STAGIONE, LIGA) == Copertura(1, 0, 0)
    assert copertura(sessione, STAGIONE, 999) == Copertura(0, 0, 0)


def _script():
    percorso = Path(__file__).resolve().parents[2] / "scripts" / "prova_stagione.py"
    spec = importlib.util.spec_from_file_location("prova_stagione_script", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize("valore", ["137", "0"])
def test_script_rifiuta_campionato_non_valido(valore, capsys):
    codice = _script().main(["--stagione", "2025", "--campionato", valore])

    assert codice == 2
    err = capsys.readouterr().err
    assert "non valido" in err and "135 o 140" in err


def test_script_rifiuta_campionato_non_numerico():
    with pytest.raises(SystemExit):
        _script().main(["--stagione", "2025", "--campionato", "abc"])


def test_script_liga_stampa_intestazione_e_copertura(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'prova.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    with modulo_sessione.apri(url) as s:
        anagrafica(s)
        aggiungi_partita(s, 10, 30, gialli={14: 1}, competizione=LIGA)
        aggiungi_partita(s, 11, 31)  # Serie A: non appare nella prova Liga

    codice = _script().main(["--stagione", str(STAGIONE), "--campionato", "140"])

    fuori = capsys.readouterr().out
    assert codice == 0
    assert "Liga" in fuori
    assert "Partite valutate: 1" in fuori
    assert "Con arbitro: 0/1; con griglia dei titolari: 0/1" in fuori


def test_script_predefinito_serie_a(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'prova.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    with modulo_sessione.apri(url) as s:
        anagrafica(s)
        aggiungi_partita(s, 10, 30)

    codice = _script().main(["--stagione", str(STAGIONE)])

    fuori = capsys.readouterr().out
    assert codice == 0
    assert "Serie A" in fuori
    assert "Partite valutate: 1" in fuori
