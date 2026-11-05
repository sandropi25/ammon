from datetime import datetime, timedelta, timezone

from conftest import FonteFinta, partita_dati
from sqlalchemy import select

from ammonizioni.caricamento import storico
from ammonizioni.config import COMPETIZIONI, STAGIONE_CORRENTE, STAGIONI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Partita, Presenza, UltimoAggiornamento
from ammonizioni.caricamento.notturno import salva_partita

OGGI = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
CARICATE = storico._COMPETIZIONI_CARICATE  # Liga e Copa del Rey entrano con il Task 5


def _salva(s, *partite):
    for p in partite:
        salva_partita(s, p)
    s.commit()


def test_storico_prima_le_squadre_della_prossima_giornata(sessione):
    giorno = lambda n: OGGI - timedelta(days=n)
    _salva(
        sessione,
        # prossima giornata di Serie A: giocano le squadre 3 e 4
        partita_dati(100, OGGI + timedelta(days=2), casa=(3, "C"), trasferta=(4, "D"), stato="NS"),
        # troppo in là: le squadre 11 e 12 non contano
        partita_dati(101, OGGI + timedelta(days=9), casa=(11, "K"), trasferta=(12, "L"), stato="NS"),
        # giocate, da scaricare
        partita_dati(10, giorno(1), casa=(5, "E"), trasferta=(6, "F")),
        partita_dati(11, giorno(5), casa=(3, "C"), trasferta=(7, "G")),
        partita_dati(12, giorno(9), casa=(8, "H"), trasferta=(9, "I")),
        partita_dati(13, giorno(30), casa=(4, "D"), trasferta=(13, "M"), competizione_id=137),
        partita_dati(14, giorno(2), casa=(11, "K"), trasferta=(14, "N")),
        # da escludere: già scaricata, stagione fuori storico, competizione non coperta
        partita_dati(20, giorno(3), casa=(3, "C"), trasferta=(7, "G")),
        partita_dati(21, giorno(4), casa=(3, "C"), trasferta=(7, "G"), stagione=2023),
        partita_dati(22, giorno(6), casa=(3, "C"), trasferta=(7, "G"), competizione_id=999),
    )
    sessione.get(Partita, 20).statistiche_scaricate = True
    sessione.commit()

    # prima 11 e 13 (squadre 3 e 4, dalla più recente), poi 10, 14, 12 (dalla più recente)
    assert storico.prossime_da_scaricare(sessione, OGGI) == [11, 13, 10, 14, 12]


def test_storico_prende_anche_le_partite_finite_ai_supplementari_o_ai_rigori(sessione):
    _salva(
        sessione,
        partita_dati(30, OGGI - timedelta(days=1), competizione_id=137, stato="AET"),
        partita_dati(31, OGGI - timedelta(days=2), competizione_id=2, stato="PEN"),
        partita_dati(32, OGGI - timedelta(days=3), stato="FT"),
        partita_dati(33, OGGI - timedelta(days=4), stato="PST"),  # non giocata: esclusa
    )
    assert storico.prossime_da_scaricare(sessione, OGGI) == [30, 31, 32]


def test_coda_storico_tutte_le_coppie_tranne_il_calendario_notturno(sessione):
    coda = storico.coda_storico(sessione, OGGI)
    assert len(coda) == len(CARICATE) * len(STAGIONI) - 1
    assert (COMPETIZIONI["serie_a"], STAGIONE_CORRENTE) not in coda
    assert [st for _, st in coda] == sorted((st for _, st in coda), reverse=True)


def test_coda_storico_salta_i_calendari_gia_scaricati(sessione):
    repo.scrivi_impostazione(sessione, "calendari_scaricati", [[137, 2025], [2, 2024]])
    coda = storico.coda_storico(sessione, OGGI)
    assert (137, 2025) not in coda and (2, 2024) not in coda
    assert len(coda) == len(CARICATE) * len(STAGIONI) - 3


def test_calendari_stagione_corrente_non_serie_a_riscaricati_dopo_7_giorni(sessione):
    tutti = [
        [c, st] for st in STAGIONI for c in CARICATE
        if (c, st) != (135, STAGIONE_CORRENTE)
    ]
    repo.scrivi_impostazione(sessione, "calendari_scaricati", tutti)
    repo.scrivi_impostazione(
        sessione,
        "calendari_scaricati_il",
        {
            "137-2026": (OGGI - timedelta(days=8)).isoformat(),   # scaduto
            "2-2026": (OGGI - timedelta(days=2)).isoformat(),     # recente
            "137-2025": (OGGI - timedelta(days=300)).isoformat(),  # passata: mai
        },
    )
    coda = storico.coda_storico(sessione, OGGI)
    assert (137, 2026) in coda
    assert (2, 2026) not in coda
    assert (137, 2025) not in coda
    # data ignota per la stagione corrente: da riscaricare; stagioni passate mai
    assert (3, 2026) in coda and (3, 2025) not in coda
    assert (135, 2026) not in coda


def test_avanza_scarica_calendari_poi_statistiche(sessione):
    base = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    calendari = {
        (137, 2025): [partita_dati(1, base, competizione_id=137, stagione=2025)],
        (135, 2025): [partita_dati(2, base + timedelta(days=1), stagione=2025)],
    }
    fonte = FonteFinta(calendari=calendari)
    r = storico.avanza(sessione, fonte)
    assert r.completo is True
    assert r.partite_aggiornate == 2
    assert r.richieste_usate == len(CARICATE) * len(STAGIONI) - 1 + 2
    nomi = [c[0] for c in fonte.chiamate]
    assert nomi == ["partite"] * 14 + ["statistiche"] * 2
    assert [c[1] for c in fonte.chiamate if c[0] == "statistiche"] == [2, 1]  # più recente prima
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == 14
    assert repo.ultimo_aggiornamento(sessione, "storico") is not None

    # secondo giro: niente da fare
    fonte2 = FonteFinta(calendari=calendari)
    r2 = storico.avanza(sessione, fonte2)
    assert (r2.completo, r2.richieste_usate, fonte2.chiamate) == (True, 0, [])


def test_avanza_limite_a_meta_salva_il_parziale(sessione):
    base = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    calendari = {(135, 2025): [partita_dati(i, base + timedelta(days=i), stagione=2025) for i in (1, 2, 3)]}
    fonte = FonteFinta(calendari=calendari, limite_dopo=14 + 1)  # 14 calendari + 1 partita
    r = storico.avanza(sessione, fonte)
    assert r.completo is False
    assert r.partite_aggiornate == 1
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == 14
    assert len({p.partita_id for p in sessione.scalars(select(Presenza))}) == 1
    assert sessione.get(UltimoAggiornamento, "storico").completo is False


def test_avanza_limite_durante_i_calendari(sessione):
    fonte = FonteFinta(calendari={}, limite_dopo=3)
    r = storico.avanza(sessione, fonte)
    assert r.completo is False
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == 3


def test_avanza_calendario_con_errore_saltato(sessione, caplog):
    class FonteCalendarioRotto(FonteFinta):
        def partite(self, competizione_id, stagione):
            if (competizione_id, stagione) == (137, 2025):
                self._chiamata("partite", competizione_id, stagione)
                from ammonizioni.fonti.base import ErroreFonte

                raise ErroreFonte("calendario rotto")
            return super().partite(competizione_id, stagione)

    fonte = FonteCalendarioRotto(calendari={})
    r = storico.avanza(sessione, fonte)
    assert r.completo is True
    assert [137, 2025] not in repo.leggi_impostazione(sessione, "calendari_scaricati")
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == 13
    assert any("137" in x.getMessage() for x in caplog.records)
