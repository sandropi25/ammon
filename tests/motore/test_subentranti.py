from datetime import datetime, timedelta, timezone
import pytest
from costruttori import medie_standard, riga

from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra
from ammonizioni.motore import subentranti
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.subentranti import (
    fattori_tendenza,
    profilo_subentro,
    sfavorita,
    tendenza_cambi,
    tendenze_cambi,
    titolare_da_sostituire,
)
from ammonizioni.motore.tipi import ContestoInfo, DatiPartita, Titolare

DATA = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def _panchine(entra: int, totale: int, minuti: int = 25):
    return [riga(titolare=False, minuti=minuti if i < entra else 0) for i in range(totale)]


# --- A1: profilo di subentro -------------------------------------------------------

def test_entra_7_volte_su_10():
    p = profilo_subentro(5, "F", _panchine(7, 10))
    assert p.panchine == 10 and p.ingressi == 7
    assert 0.6 <= p.probabilita_ingresso <= 0.7
    assert p.minuti_medi == pytest.approx(25)


def test_terzo_portiere_non_entra_mai():
    p = profilo_subentro(5, "G", _panchine(0, 15))
    assert p.probabilita_ingresso < 0.05
    assert p.minuti_medi == subentranti.MINUTI_SUBENTRO_PREDEFINITI


def test_nessuna_panchina_nessun_profilo():
    assert profilo_subentro(5, "M", [riga(titolare=True)] * 3) is None
    assert profilo_subentro(5, "M", []) is None


def test_contano_solo_le_ultime_15_panchine_e_anche_un_minuto():
    vecchie = _panchine(0, 10)
    recenti = _panchine(15, 15, minuti=1)  # entra sempre, anche solo 1 minuto
    p = profilo_subentro(5, "M", vecchie + recenti)
    assert p.panchine == 15 and p.ingressi == 15
    assert p.minuti_medi == pytest.approx(1)


# --- A2: tendenza dei cambi e squadra sfavorita ------------------------------------

def _dati(prob=None, punti=None):
    return DatiPartita(
        partita_id=100, data=DATA, stagione=2026, casa_id=1, trasferta_id=2,
        nomi_squadre={1: "Casa", 2: "Ospiti"}, titolari=[], storico={}, arbitro=None,
        medie=medie_standard(),
        contesto=ContestoInfo(False, False, {}, 0, None, punti_partita=punti or {}),
        duelli_manuali={}, prob_vittoria=prob or {},
    )


def test_sfavorita_dalle_quote():
    dati = _dati(prob={1: 0.25, 2: 0.45})
    assert sfavorita(dati, 1) and not sfavorita(dati, 2)
    vicine = _dati(prob={1: 0.36, 2: 0.40})
    assert not sfavorita(vicine, 1)


def test_sfavorita_dalla_classifica_senza_quote():
    dati = _dati(punti={1: 1.0, 2: 2.0})
    assert sfavorita(dati, 1) and not sfavorita(dati, 2)
    assert not sfavorita(_dati(punti={1: 1.8, 2: 2.0}), 1)


def test_quote_prevalgono_sulla_classifica():
    dati = _dati(prob={1: 0.5, 2: 0.25}, punti={1: 1.0, 2: 2.5})
    assert not sfavorita(dati, 1)


def test_senza_quote_ne_classifica_non_sfavorita():
    assert not sfavorita(_dati(), 1)


def test_sfavorita_attaccanti_pesano_di_piu():
    quote = {"F": 0.6, "M": 0.2, "D": 0.2}
    neutri = fattori_tendenza(quote, False, Pesi())
    assert all(v == 1.0 for v in neutri.values())
    f = fattori_tendenza(quote, True, Pesi())
    assert f["F"] > 1 > f["M"] > f["D"]
    # la somma pesata delle quote resta 1 (si redistribuiscono i cambi, non se ne aggiungono)
    assert sum(quote[r] * f[r] for r in quote) == pytest.approx(1.0)


def test_titolare_da_sostituire_stesso_ruolo_piu_sostituito():
    t = [
        Titolare(1, "Ala sempre in campo", 1, "F", "4:1", None),
        Titolare(2, "Ala spesso fuori", 1, "F", "4:2", None),
        Titolare(3, "Ala un po' fuori", 1, "F", "4:3", None),
        Titolare(4, "Mediano fuori", 1, "M", "3:1", None),
        Titolare(5, "Punta avversaria", 2, "F", "4:1", None),
    ]
    storico = {
        1: [riga(minuti=90)] * 5,
        2: [riga(minuti=60)] * 5,
        3: [riga(minuti=75)] * 5,
        4: [riga(minuti=50)] * 5,
        5: [riga(minuti=30)] * 5,
    }
    panchinaro = Titolare(9, "Punta di riserva", 1, "F", None, None)
    assert titolare_da_sostituire(panchinaro, t, storico).giocatore_id == 2


def test_nessun_titolare_sostituito_nessun_nome():
    t = [Titolare(1, "Difensore", 1, "D", "2:1", None)]
    storico = {1: [riga(minuti=90)] * 5 + [riga(minuti=40, rossi=1)]}  # uscito per rosso
    assert titolare_da_sostituire(Titolare(9, "Riserva", 1, "D", None, None), t, storico) is None


def _popola_cambi(s, n_partite=12):
    s.add_all([Squadra(id=1, nome="A"), Squadra(id=2, nome="B")])
    ruoli = {101: "F", 102: "F", 103: "D", 104: "M", 105: None}
    for gid, ruolo in ruoli.items():
        s.add(Giocatore(id=gid, nome=f"G{gid}", ruolo=ruolo or "F"))
    s.flush()
    inizio = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    for i in range(1, n_partite + 1):
        s.add(Partita(id=i, data_utc=inizio + timedelta(days=7 * i), competizione_id=135,
                      stagione=2026, casa_id=1, trasferta_id=2, stato="FT",
                      statistiche_scaricate=True))
        s.flush()
        # la 1 e la 2 (più vecchie) hanno un difensore entrato: fuori dalle ultime 10
        entrati = [101, 102, 105] if i > 2 else [103, 103]
        for k, gid in enumerate(dict.fromkeys(entrati)):
            s.add(Presenza(partita_id=i, giocatore_id=gid, squadra_id=1, titolare=False,
                           minuti=20, ruolo=None))
        s.add(Presenza(partita_id=i, giocatore_id=104, squadra_id=1, titolare=False, minuti=0))
    s.flush()


def test_tendenza_cambi_squadra_che_fa_entrare_attaccanti(sessione):
    _popola_cambi(sessione)
    quote = tendenza_cambi(sessione, 1, datetime(2026, 12, 31, tzinfo=timezone.utc), 2026)
    assert quote == {"F": pytest.approx(1.0)}  # 105 senza ruolo nella presenza: quello del giocatore
    assert tendenze_cambi(sessione, [1, 2], DATA, 2026)[2] == {}


def test_tendenza_cambi_conta_solo_ultime_10(sessione):
    _popola_cambi(sessione, n_partite=11)  # partite 3..11 + la 2 nelle ultime 10
    quote = tendenza_cambi(sessione, 1, DATA, 2026)
    assert quote["D"] == pytest.approx(1 / 28)
    assert quote["F"] == pytest.approx(27 / 28)


def test_tendenza_senza_partite():
    assert tendenze_cambi(None, [], DATA, 2026) == {}
