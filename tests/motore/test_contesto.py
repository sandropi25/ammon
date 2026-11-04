from costruttori import medie_standard

from ammonizioni.motore.fattori.contesto import fattore_contesto, posta_in_classifica
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import ContestoInfo


def _ctx(**kw):
    valori = dict(
        rivalita=False,
        campo_caldo=False,
        posta={},
        precedenti_n=0,
        precedenti_gialli_medi=None,
    )
    valori.update(kw)
    return ContestoInfo(**valori)


def test_derby_alza_contesto():
    f = fattore_contesto(_ctx(rivalita=True), 1, medie_standard(), Pesi())
    assert f.nome == "contesto"
    assert f.valore == Pesi().rivalita
    assert f.motivazione == "Derby/rivalità"


def test_contesto_neutro():
    f = fattore_contesto(_ctx(), 1, medie_standard(), Pesi())
    assert f.valore == 1.0
    assert f.motivazione is None


def test_contesto_motivazioni_unite_in_ordine():
    ctx = _ctx(
        rivalita=True,
        campo_caldo=True,
        posta={1: "salvezza"},
        precedenti_n=5,
        precedenti_gialli_medi=8.4,
    )
    f = fattore_contesto(ctx, 1, medie_standard(), Pesi())
    assert f.motivazione == (
        "Derby/rivalità · Campo caldo · In lotta per la salvezza · Precedenti nervosi"
    )
    assert f.n_dati == 5
    assert f.valore == Pesi().limiti_fattore[1]  # prodotto > 1.6, limitato


def test_contesto_articoli_posta():
    m, p = medie_standard(), Pesi()
    assert fattore_contesto(_ctx(posta={1: "titolo"}), 1, m, p).motivazione == "In lotta per il titolo"
    assert fattore_contesto(_ctx(posta={1: "Europa"}), 1, m, p).motivazione == "In lotta per l'Europa"
    assert fattore_contesto(_ctx(posta={2: "titolo"}), 1, m, p).motivazione is None


def test_precedenti_pochi_dati_attenuati_e_senza_motivazione():
    m, p = medie_standard(), Pesi()
    f = fattore_contesto(_ctx(precedenti_n=2, precedenti_gialli_medi=6.3), 1, m, p)
    pieno = fattore_contesto(_ctx(precedenti_n=3, precedenti_gialli_medi=6.3), 1, m, p)
    assert 1 < f.valore < pieno.valore
    assert f.motivazione is None
    assert pieno.motivazione == "Precedenti nervosi"


def test_precedenti_gialli_none_moltiplicatore_1():
    f = fattore_contesto(_ctx(precedenti_n=5), 1, medie_standard(), Pesi())
    assert f.valore == 1.0


def _girone(squadre: int, escludi_ultima_giornata: bool = False):
    """Girone all'italiana a senso unico: la squadra con id minore batte sempre l'altra.

    Con `squadre` squadre ognuna gioca squadre-1 partite; la squadra i ha 3*(squadre-i) punti.
    """
    return [(i, j, 1, 0) for i in range(1, squadre + 1) for j in range(i + 1, squadre + 1)]


def test_posta_salvezza_dopo_giornata_19():
    partite = _girone(20)  # 19 partite a squadra; 17a = squadra 17 con 9 punti
    assert posta_in_classifica(partite, 16) == "salvezza"  # 12 punti, a 3 dalla 17a
    assert posta_in_classifica(partite, 14) is None  # 18 punti, troppo lontana


def test_posta_titolo_e_europa():
    partite = _girone(20)  # punti: squadra k -> 3*(20-k); 1a=57, 4a=48, 6a=42
    assert posta_in_classifica(partite, 2) == "titolo"  # 54
    assert posta_in_classifica(partite, 3) == "Europa"  # 51, a 3 dalla 4a
    assert posta_in_classifica(partite, 7) == "Europa"  # 39, a 3 dalla 6a
    assert posta_in_classifica(partite, 10) is None  # 30


def test_nessuna_posta_prima_di_giornata_19():
    partite = _girone(19)  # 18 partite a squadra
    assert posta_in_classifica(partite, 2) is None
    assert posta_in_classifica(partite, 17) is None


def test_posta_squadra_assente_none():
    assert posta_in_classifica(_girone(20), 999) is None


def test_posta_non_dipende_dall_ordine_delle_partite():
    partite = _girone(20)
    assert posta_in_classifica(list(reversed(partite)), 3) == posta_in_classifica(partite, 3)
