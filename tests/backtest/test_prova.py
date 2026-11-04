from datetime import datetime, timedelta, timezone

import pytest

from ammonizioni.backtest.prova import RisultatoProva, prova_stagione
from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra

SERIE_A = 135
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
