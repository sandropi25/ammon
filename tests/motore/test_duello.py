import pytest
from costruttori import medie_standard, riga

from ammonizioni.motore.fattori.duello import avversario_diretto, fattore_duello
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import Titolare

CASA, TRASF = 1, 2


def _t(gid, ruolo, griglia, squadra, nome=None):
    return Titolare(gid, nome or f"Giocatore {gid}", squadra, ruolo, griglia, None)


def _casa_433():
    return [
        _t(1, "G", "1:1", CASA),
        _t(2, "D", "2:1", CASA),
        _t(3, "D", "2:2", CASA),
        _t(4, "D", "2:3", CASA),
        _t(5, "D", "2:4", CASA),
        _t(6, "M", "3:1", CASA),
        _t(7, "M", "3:2", CASA),
        _t(8, "M", "3:3", CASA),
        _t(9, "F", "4:1", CASA),
        _t(10, "F", "4:2", CASA),
        _t(11, "F", "4:3", CASA),
    ]


def _trasferta_442():
    return [
        _t(101, "G", "1:1", TRASF),
        _t(102, "D", "2:1", TRASF),
        _t(103, "D", "2:2", TRASF),
        _t(104, "D", "2:3", TRASF),
        _t(105, "D", "2:4", TRASF),
        _t(106, "M", "3:1", TRASF),
        _t(107, "M", "3:2", TRASF),
        _t(108, "M", "3:3", TRASF),
        _t(109, "M", "3:4", TRASF),
        _t(110, "F", "4:1", TRASF),
        _t(111, "F", "4:2", TRASF),
    ]


def _per_id(squadra, gid):
    return next(t for t in squadra if t.giocatore_id == gid)


def test_terzino_destro_contro_esterno_sinistro():
    casa, trasf = _casa_433(), _trasferta_442()
    # terzino all'estremo (corsia 1.0) -> specchio 0.0 -> primo attaccante (4:1)
    assert avversario_diretto(_per_id(casa, 5), trasf, None, casa) == 110
    # terzino all'estremo opposto (corsia 0.0) -> specchio 1.0 -> secondo attaccante (4:2)
    assert avversario_diretto(_per_id(casa, 2), trasf, None, casa) == 111
    # centrocampista (3:3, corsia 1.0) -> mediano alla corsia 0 (3:1)
    assert avversario_diretto(_per_id(casa, 8), trasf, None, casa) == 106
    # attaccante (4:1, corsia 0) -> difensore alla corsia 1 (2:4)
    assert avversario_diretto(_per_id(casa, 9), trasf, None, casa) == 105
    # simmetria: dal 4-4-2 verso il 4-3-3, esterno di centrocampo 3:4 (corsia 1) -> 3:1
    assert avversario_diretto(_per_id(trasf, 109), casa, None, trasf) == 6


def test_giocatore_solo_nella_riga_ha_corsia_centrale():
    casa = _casa_433() + [_t(12, "M", "5:1", CASA)]
    trasf = _trasferta_442()
    # corsia 0.5 -> specchio 0.5: tra 3:2 (0.333) e 3:3 (0.667) pari distanza -> id minore
    assert avversario_diretto(_per_id(casa, 12), trasf, None, casa) == 107


def test_linea_opposta_vuota_usa_centrocampo():
    casa = _casa_433()
    trasf = [t for t in _trasferta_442() if t.ruolo != "F"]
    # terzino 2:4 (corsia 1.0) senza attaccanti avversari -> centrocampo, corsia 0 -> 3:1
    assert avversario_diretto(_per_id(casa, 5), trasf, None, casa) == 106


def test_portiere_nessun_avversario():
    assert avversario_diretto(_per_id(_casa_433(), 1), _trasferta_442(), None, _casa_433()) is None


def test_duello_manuale_ha_precedenza():
    casa, trasf = _casa_433(), _trasferta_442()
    assert avversario_diretto(_per_id(casa, 5), trasf, 108) == 108
    # anche senza griglia
    assert avversario_diretto(_t(50, "D", None, CASA), trasf, 108) == 108


def test_senza_griglia_nessun_avversario():
    assert avversario_diretto(_t(50, "D", None, CASA), _trasferta_442(), None, _casa_433()) is None


def test_avversari_senza_griglia_ignorati():
    casa = _casa_433()
    trasf = [_t(200, "F", None, TRASF)] + [t for t in _trasferta_442() if t.ruolo != "F"]
    # nessun attaccante con griglia -> centrocampo
    assert avversario_diretto(_per_id(casa, 5), trasf, None, casa) == 106


def _avv(ruolo="F", nome="Rossi"):
    return _t(300, ruolo, "4:1", TRASF, nome)


def _storico_medio():
    """10 partite da 90': fs 1,5/90, dribbling 1,8/90, ga 0,4/90, voto 6,2 costante."""
    gol = [1, 0, 1, 0, 0] * 2
    fs = [1, 2] * 5
    drib = [2, 2, 2, 2, 1] * 2
    return [
        riga(gol=g, falli_subiti=f, dribbling_tentati=d, voto=6.2)
        for g, f, d in zip(gol, fs, drib)
    ]


def test_avversario_nella_media_fattore_circa_1():
    f = fattore_duello(_avv(), _storico_medio(), medie_standard(), Pesi())
    assert f.nome == "duello"
    assert f.valore == pytest.approx(1.0, abs=0.01)
    assert f.motivazione is None
    assert f.n_dati == 10


def test_dribblatore_in_forma_alza_il_fattore():
    vecchie = [riga(gol=0, falli_subiti=3, dribbling_tentati=4, voto=6.0) for _ in range(5)]
    recenti = [riga(gol=1, falli_subiti=3, dribbling_tentati=4, voto=7.0) for _ in range(5)]
    f = fattore_duello(_avv(nome="Leao"), vecchie + recenti, medie_standard(), Pesi())
    assert f.valore > 1.0
    assert "marca" in f.motivazione
    assert "gol nelle ultime" in f.motivazione
    assert f.motivazione == "marca Leao, 3 gol nelle ultime 3"


def test_motivazione_falli_subiti_senza_gol_recenti():
    righe = [riga(gol=0, falli_subiti=3 if i % 2 == 0 else 2,
                  dribbling_tentati=2, voto=6.2) for i in range(10)]
    # fs90 = 25/10 = 2,5 ; dribbling 2/1,8 -> valore > 1,05
    f = fattore_duello(_avv(nome="Rossi"), righe, medie_standard(), Pesi())
    assert f.valore >= 1.05
    assert f.motivazione == "marca Rossi, 2,5 falli subiti a partita"


def test_gol_nelle_ultime_conta_solo_le_ultime_tre():
    # gol solo nelle ultime 3 partite: 1 + 0 + 2 = 3 ; la partita piu' vecchia non conta
    gol = [5, 0, 0, 0, 0, 0, 0, 1, 0, 2]
    righe = [riga(gol=g, falli_subiti=3, dribbling_tentati=2, voto=6.2) for g in gol]
    f = fattore_duello(_avv(nome="Rossi"), righe, medie_standard(), Pesi())
    assert f.motivazione == "marca Rossi, 3 gol nelle ultime 3"


def test_fattore_limitato_a_1_6():
    righe = [riga(gol=0, falli_subiti=9, dribbling_tentati=9, voto=6.2) for _ in range(10)]
    f = fattore_duello(_avv(), righe, medie_standard(), Pesi())
    assert f.valore == pytest.approx(1.6)


def test_pochi_dati_attenuano():
    righe = [riga(gol=0, falli_subiti=3, dribbling_tentati=1.8) for _ in range(2)]
    pieno = fattore_duello(_avv(), righe * 3, medie_standard(), Pesi())
    poco = fattore_duello(_avv(), righe, medie_standard(), Pesi())
    assert 1.0 < poco.valore < pieno.valore
    assert poco.valore == pytest.approx(1 + (pieno.valore - 1) * 0.2, abs=0.02)


def test_nessun_avversario_fattore_neutro():
    f = fattore_duello(None, [], medie_standard(), Pesi())
    assert (f.nome, f.valore, f.motivazione, f.n_dati) == ("duello", 1.0, None, 0)


def test_avversario_senza_minuti_neutro():
    f = fattore_duello(_avv(), [riga(minuti=0)], medie_standard(), Pesi())
    assert f.valore == pytest.approx(1.0)
    assert f.motivazione is None
