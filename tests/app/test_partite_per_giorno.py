from datetime import datetime, timezone

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import componenti
from componenti import RigaPartita, raggruppa_per_giorno


def _riga(pid, utc):
    return RigaPartita(
        id=pid, quando="", giornata=1, casa=f"C{pid}", trasferta=f"T{pid}", arbitro=None,
        calda=False, formazioni="probabili", ora=componenti.ora_italiana(utc), data_utc=utc,
    )


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# venerdì 6 novembre 2026, ora solare (UTC+1)
ADESSO = _utc(2026, 11, 6, 9, 0)


def test_etichette_oggi_domani_e_altri_giorni():
    righe = [
        _riga(1, _utc(2026, 11, 8, 19, 45)),   # sabato 20:45 Roma
        _riga(2, _utc(2026, 11, 6, 19, 45)),   # oggi
        _riga(3, _utc(2026, 11, 7, 14, 0)),    # domani
    ]
    titoli = [t for t, _ in raggruppa_per_giorno(righe, ADESSO)]
    assert titoli == [
        "Oggi · venerdì 6 novembre 2026",
        "Domani · sabato 7 novembre 2026",
        "domenica 8 novembre 2026",
    ]


def test_ordine_per_orario_dentro_il_giorno_e_orario_mostrato():
    righe = [
        _riga(1, _utc(2026, 11, 8, 19, 45)),
        _riga(2, _utc(2026, 11, 8, 11, 30)),
        _riga(3, _utc(2026, 11, 8, 17, 0)),
    ]
    (titolo, del_giorno), = raggruppa_per_giorno(righe, ADESSO)
    assert [r.id for r in del_giorno] == [2, 3, 1]
    assert [r.ora for r in del_giorno] == ["12:30", "18:00", "20:45"]


def test_giorni_in_ordine_cronologico_anche_se_in_input_sono_sparsi():
    righe = [_riga(1, _utc(2026, 11, 9, 12)), _riga(2, _utc(2026, 11, 7, 12)), _riga(3, _utc(2026, 11, 9, 8))]
    gruppi = raggruppa_per_giorno(righe, ADESSO)
    assert [t for t, _ in gruppi] == ["Domani · sabato 7 novembre 2026", "lunedì 9 novembre 2026"]
    assert [r.id for r in gruppi[1][1]] == [3, 1]


def test_dopo_mezzanotte_a_roma_cade_nel_giorno_dopo():
    # 23:30 UTC del 6/11 = 00:30 del 7/11 a Roma: non e' "Oggi" ma "Domani"
    tardi = _riga(1, _utc(2026, 11, 6, 23, 30))
    prima = _riga(2, _utc(2026, 11, 6, 22, 30))  # 23:30 del 6/11 a Roma: ancora oggi
    gruppi = raggruppa_per_giorno([tardi, prima], ADESSO)
    assert [t for t, _ in gruppi] == ["Oggi · venerdì 6 novembre 2026", "Domani · sabato 7 novembre 2026"]
    assert gruppi[1][1][0].ora == "00:30"


def test_oggi_si_calcola_a_roma_non_in_utc():
    # alle 23:30 UTC del 6/11 a Roma e' gia' il 7/11: la partita del 7/11 e' "Oggi"
    adesso = _utc(2026, 11, 6, 23, 30)
    (titolo, _), = raggruppa_per_giorno([_riga(1, _utc(2026, 11, 7, 12))], adesso)
    assert titolo == "Oggi · sabato 7 novembre 2026"


def test_ora_legale_e_nomi_italiani():
    # luglio: UTC+2; 18:45 UTC = 20:45 Roma
    r = _riga(1, _utc(2026, 7, 5, 18, 45))
    assert r.ora == "20:45"
    (titolo, _), = raggruppa_per_giorno([r], _utc(2026, 7, 1, 10))
    assert titolo == "domenica 5 luglio 2026"


def test_nessuna_partita_nessun_gruppo():
    assert raggruppa_per_giorno([], ADESSO) == []
