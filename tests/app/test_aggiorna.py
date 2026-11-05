import os
import sys
import types
from pathlib import Path

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import aggiorna

# moduli finti: il test non deve mai togliere dalla memoria il motore vero
PACCHETTO = "motore_finto_xyz"
APP = ("pagina_finta_xyz",)


def _carica_finti():
    sys.modules[PACCHETTO] = types.ModuleType(PACCHETTO)
    sys.modules[PACCHETTO + ".dati"] = types.ModuleType(PACCHETTO + ".dati")
    sys.modules[APP[0]] = types.ModuleType(APP[0])
    sys.modules["altro_modulo_xyz"] = types.ModuleType("altro_modulo_xyz")


def _chiama(cartella, svuota=None):
    return aggiorna.ricarica_se_cambiato(svuota, cartella=cartella, pacchetto=PACCHETTO, moduli_app=APP)


def test_prima_chiamata_toglie_il_motore_in_memoria(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(aggiorna, "_firma", None)
    _carica_finti()
    svuotata = []
    assert _chiama(tmp_path, lambda: svuotata.append(1))
    assert PACCHETTO not in sys.modules and PACCHETTO + ".dati" not in sys.modules
    assert APP[0] not in sys.modules
    assert "altro_modulo_xyz" in sys.modules  # solo motore e moduli dell'app
    assert svuotata == [1]


def test_senza_modifiche_non_tocca_niente(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(aggiorna, "_firma", None)
    _chiama(tmp_path)
    _carica_finti()
    assert not _chiama(tmp_path)
    assert APP[0] in sys.modules


def test_file_modificato_o_aggiunto_ricarica(tmp_path, monkeypatch):
    sorgente = tmp_path / "a.py"
    sorgente.write_text("x = 1\n")
    monkeypatch.setattr(aggiorna, "_firma", None)
    _chiama(tmp_path)
    stat = sorgente.stat()
    os.utime(sorgente, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    _carica_finti()
    assert _chiama(tmp_path)
    assert APP[0] not in sys.modules
    (tmp_path / "b.py").write_text("y = 2\n")
    assert _chiama(tmp_path)


def test_i_valori_predefiniti_puntano_al_motore_vero():
    assert aggiorna.SORGENTI.name == "ammonizioni" and aggiorna.SORGENTI.is_dir()
    assert "componenti" in aggiorna.MODULI_APP and "cache_dati" in aggiorna.MODULI_APP


def test_ogni_pagina_lo_chiama_prima_degli_import_dell_app():
    radice = Path(aggiorna.__file__).resolve().parent
    for pagina in [radice / "Partite.py", *sorted((radice / "pages").glob("*.py"))]:
        testo = pagina.read_text(encoding="utf-8")
        assert "ricarica_se_cambiato(" in testo, pagina.name
        primo_import_app = min(
            testo.index(f"import {m}") for m in ("componenti", "cache_dati") if f"import {m}" in testo
        )
        assert testo.index("ricarica_se_cambiato(") < primo_import_app, pagina.name
