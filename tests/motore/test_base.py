import math
from datetime import datetime, timedelta, timezone

import pytest
from costruttori import medie_standard, riga

from ammonizioni.motore.fattori.base import base_giocatore, tasso_base90
from ammonizioni.motore.pesi import Pesi


def _partite(n, stagione, gialli_per_partita, inizio, **kw):
    """n partite consecutive con data crescente e stesso numero di gialli."""
    return [
        riga(
            stagione=stagione,
            gialli=gialli_per_partita[i] if isinstance(gialli_per_partita, list) else gialli_per_partita,
            data=inizio + timedelta(days=i),
            **kw,
        )
        for i in range(n)
    ]


INIZIO = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_giocatore_senza_storico_usa_media_ruolo():
    f = base_giocatore([], "D", medie_standard(), 2026, Pesi())
    assert f.n_dati == 0
    assert f.valore == pytest.approx(1 - math.exp(-medie_standard().per_ruolo["D"].gialli90))
    assert f.motivazione is None


def test_peso_nullo_sull_unica_stagione_giocata_usa_la_media_del_ruolo():
    """Pesi validi (somma > 0) ma la sola stagione con minuti ha peso 0: niente divisione
    per zero, il tasso parte dalla media del ruolo."""
    pesi = Pesi(pesi_stagioni=(0.0, 0.5, 0.5))
    storico = _partite(3, 2026, 1, INIZIO)
    senza_dati = Pesi(pesi_stagioni=(0.0, 0.5, 0.5), minuti_prior=1e12)
    f = base_giocatore(storico, "D", medie_standard(), 2026, pesi)
    assert 0 < f.valore < 1
    # con un restringimento enorme resta solo la media del ruolo
    assert tasso_base90(storico, "D", medie_standard(), 2026, senza_dati) == pytest.approx(
        medie_standard().per_ruolo["D"].gialli90
    )


def test_ultime_5_solo_partite_giocate():
    """Le panchine (0 minuti) piu' recenti non tolgono il peso doppio alle ultime 5 giocate."""
    giocate = _partite(10, 2026, [0] * 5 + [1, 1, 0, 0, 0], INIZIO)
    panchine = _partite(5, 2026, 0, INIZIO + timedelta(days=20), minuti=0)
    pesi = Pesi()
    assert tasso_base90(giocate + panchine, "D", medie_standard(), 2026, pesi) == pytest.approx(
        tasso_base90(giocate, "D", medie_standard(), 2026, pesi)
    )


def test_ultime_5_pesano_doppio():
    # 10 partite, 2 gialli: nelle ultime 5 oppure nelle prime 5
    in_ultime = [0] * 5 + [1, 1, 0, 0, 0]
    in_prime = [1, 1, 0, 0, 0] + [0] * 5
    a = base_giocatore(_partite(10, 2026, in_ultime, INIZIO), "D", medie_standard(), 2026, Pesi())
    b = base_giocatore(_partite(10, 2026, in_prime, INIZIO), "D", medie_standard(), 2026, Pesi())
    assert a.valore > b.valore


def test_ultime_5_dipendono_dalla_data_non_dall_ordine_della_lista():
    in_ultime = _partite(10, 2026, [0] * 5 + [1, 1, 0, 0, 0], INIZIO)
    mescolata = list(reversed(in_ultime))
    pesi = Pesi()
    assert tasso_base90(mescolata, "D", medie_standard(), 2026, pesi) == pytest.approx(
        tasso_base90(in_ultime, "D", medie_standard(), 2026, pesi)
    )


def test_stagione_corrente_pesa_piu_della_precedente():
    inizio_prec = datetime(2025, 9, 1, tzinfo=timezone.utc)
    # stessi gialli, ma nella corrente vs nella precedente (per l'altra stagione zero gialli)
    nella_corrente = _partite(10, 2026, [1, 1] + [0] * 8, INIZIO) + _partite(10, 2025, 0, inizio_prec)
    nella_precedente = _partite(10, 2026, 0, INIZIO) + _partite(10, 2025, [1, 1] + [0] * 8, inizio_prec)
    a = base_giocatore(nella_corrente, "D", medie_standard(), 2026, Pesi())
    b = base_giocatore(nella_precedente, "D", medie_standard(), 2026, Pesi())
    assert a.valore > b.valore


def test_pesi_rinormalizzati_sulle_stagioni_con_minuti():
    # solo la stagione precedente ha minuti: pesa 100% (non 30%)
    righe = _partite(20, 2025, [1] + [0] * 19, datetime(2025, 9, 1, tzinfo=timezone.utc))
    pesi = Pesi(minuti_prior=0.0001)  # shrinkage trascurabile
    tasso = tasso_base90(righe, "D", medie_standard(), 2026, pesi)
    assert tasso == pytest.approx(1 / 20, rel=1e-3)


def test_restringimento_al_ruolo():
    righe = _partite(10, 2026, 1, INIZIO)  # 900 minuti, tasso grezzo 1.0/90
    tasso = tasso_base90(righe, "D", medie_standard(), 2026, Pesi(bonus_ritardo=1.0))
    assert tasso == pytest.approx((1.0 * 900 + 0.20 * 900) / 1800)


def test_in_ritardo_alza_la_base_e_lo_dice():
    storico_tanti_falli_zero_gialli = _partite(10, 2026, 0, INIZIO, falli_commessi=3)
    f = base_giocatore(storico_tanti_falli_zero_gialli, "M", medie_standard(), 2026, Pesi())
    assert "in ritardo" in f.motivazione
    senza_bonus = base_giocatore(
        storico_tanti_falli_zero_gialli, "M", medie_standard(), 2026, Pesi(bonus_ritardo=1.0)
    )
    assert f.valore > senza_bonus.valore
    assert senza_bonus.motivazione is not None  # la motivazione dipende dal criterio, non dal bonus


def test_non_in_ritardo_con_pochi_falli():
    f = base_giocatore(_partite(10, 2026, 0, INIZIO, falli_commessi=1), "M", medie_standard(), 2026, Pesi())
    assert f.motivazione is None


def test_non_in_ritardo_se_i_gialli_sono_sopra_la_media():
    f = base_giocatore(_partite(10, 2026, 1, INIZIO, falli_commessi=3), "M", medie_standard(), 2026, Pesi())
    assert f.motivazione is None


def test_minuti_attesi_dalle_ultime_5_da_titolare():
    # 5 partite da titolare con 60 minuti -> p calcolata su 60/90 del tasso
    righe = _partite(5, 2026, 0, INIZIO, minuti=60)
    pesi = Pesi()
    tasso = tasso_base90(righe, "D", medie_standard(), 2026, pesi)
    f = base_giocatore(righe, "D", medie_standard(), 2026, pesi)
    assert f.valore == pytest.approx(1 - math.exp(-tasso * 60 / 90))
    assert f.n_dati == 300


def test_minuti_attesi_ignora_subentrati_e_ha_tetto_90():
    righe = _partite(3, 2026, 0, INIZIO, minuti=90) + _partite(
        3, 2026, 0, INIZIO + timedelta(days=30), minuti=10, titolare=False
    )
    pesi = Pesi()
    tasso = tasso_base90(righe, "D", medie_standard(), 2026, pesi)
    f = base_giocatore(righe, "D", medie_standard(), 2026, pesi)
    assert f.valore == pytest.approx(1 - math.exp(-tasso))


def test_nessun_titolare_assume_90():
    righe = _partite(3, 2026, 0, INIZIO, minuti=20, titolare=False)
    tasso = tasso_base90(righe, "D", medie_standard(), 2026, Pesi())
    f = base_giocatore(righe, "D", medie_standard(), 2026, Pesi())
    assert f.valore == pytest.approx(1 - math.exp(-tasso))


def test_giallo_dalla_panchina_alza_il_tasso_base():
    """Un giallo preso da chi non e' entrato (0 minuti) entra nelle somme di stagione."""
    base = _partite(5, 2026, 0, INIZIO)
    senza = tasso_base90(base, "D", medie_standard(), 2026, Pesi())
    panchina = riga(
        stagione=2026, gialli=1, minuti=0, titolare=False, data=INIZIO + timedelta(days=10)
    )
    con = tasso_base90(base + [panchina], "D", medie_standard(), 2026, Pesi())
    assert con > senza
    # l'unico giallo sui 450 minuti giocati: gialli/90 = 0,2 prima del restringimento al ruolo
    assert base_giocatore(base + [panchina], "D", medie_standard(), 2026, Pesi()).n_dati == 450


def test_ultime5_restano_sulle_partite_giocate():
    """La panchina non occupa un posto fra le ultime 5 giocate."""
    p = Pesi()
    giocate = _partite(5, 2026, [1, 0, 0, 0, 0], INIZIO)
    panchina = riga(
        stagione=2026, gialli=0, minuti=0, titolare=False, data=INIZIO + timedelta(days=10)
    )
    a = tasso_base90(giocate, "D", medie_standard(), 2026, p)
    b = tasso_base90(giocate + [panchina], "D", medie_standard(), 2026, p)
    assert b == pytest.approx(a)
