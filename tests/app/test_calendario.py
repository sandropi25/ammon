"""Calendario: giornate e giornata in corso, partite giocate (risultato, arbitro, cartellini
totali con la panchina) e da giocare, navigazione con le frecce, nessun crash senza giornate."""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ayuda_app import (  # noqa: F401
    PAGINA_CALENDARIO, RADICE, avvia, scegli_campionato, sessione_db, url_db, visibile,
)
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola

import componenti
import componenti_calendario as cal
import stile
from ammonizioni.db.modelli import Giocatore, Partita, Presenza, Squadra


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


PARTITA_DATA_DOPO = _utc(2026, 11, 9, 19, 45)


def _p(pid, giornata, data, stato="FT"):
    return (pid, giornata, data, stato)


# ---------------------------------------------------------------- logica pura

def test_giornata_in_corso_e_la_prima_con_partite_non_finite():
    c = cal.costruisci_calendario([
        _p(1, 1, _utc(2026, 9, 1)), _p(2, 2, _utc(2026, 9, 8)),
        _p(3, 3, _utc(2026, 9, 15), "NS"), _p(4, 3, _utc(2026, 9, 15, 18), "FT"),
        _p(5, 4, _utc(2026, 9, 22), "NS"),
    ])
    assert c.per_giornata
    assert [t.chiave for t in c.turni] == [1, 2, 3, 4]
    assert c.turni[c.in_corso].chiave == 3  # una partita ancora da giocare
    assert c.turni[2].ids == (3, 4) and c.turni[2].etichetta == "Giornata 3"
    assert [t.finito for t in c.turni] == [True, True, False, False]


def test_stagione_finita_in_corso_e_l_ultima_giornata():
    c = cal.costruisci_calendario([_p(1, 1, _utc(2026, 9, 1)), _p(2, 2, _utc(2026, 9, 8))])
    assert c.turni[c.in_corso].chiave == 2


def test_rinviate_e_annullate_non_tengono_aperta_la_giornata():
    c = cal.costruisci_calendario([
        _p(1, 1, _utc(2026, 9, 1)), _p(2, 1, _utc(2026, 9, 2), "PST"),
        _p(3, 2, _utc(2026, 9, 8), "CANC"), _p(4, 3, _utc(2026, 9, 15), "NS"),
    ])
    assert c.turni[c.in_corso].chiave == 3


def test_calendario_vuoto():
    c = cal.costruisci_calendario([])
    assert c.turni == () and c.in_corso is None and c.indice(5) is None


def test_indice_della_chiave_o_quella_in_corso():
    c = cal.costruisci_calendario([_p(1, 1, _utc(2026, 9, 1)), _p(2, 2, _utc(2026, 9, 8), "NS")])
    assert c.indice(1) == 0
    assert c.indice(None) == 1 and c.indice(99) == 1


def test_partita_senza_giornata_prende_quella_della_vicina_nel_tempo():
    c = cal.costruisci_calendario([
        _p(1, 5, _utc(2026, 9, 1)), _p(2, None, _utc(2026, 9, 2)), _p(3, 6, _utc(2026, 9, 8)),
    ])
    assert c.per_giornata
    assert [t.ids for t in c.turni] == [(1, 2), (3,)]


def test_senza_giornate_si_raggruppa_per_settimana_di_roma():
    # domenica 8/11 23:30 UTC = lunedì 9/11 00:30 a Roma: appartiene alla settimana dopo
    c = cal.costruisci_calendario([
        _p(1, None, _utc(2026, 11, 3, 19)), _p(2, None, _utc(2026, 11, 8, 12)),
        _p(3, None, _utc(2026, 11, 8, 23, 30), "NS"),
    ])
    assert not c.per_giornata
    assert [t.ids for t in c.turni] == [(1, 2), (3,)]
    assert c.turni[0].etichetta == "Settimana dal 2 al 8 novembre 2026"
    assert c.turni[1].etichetta == "Settimana dal 9 al 15 novembre 2026"
    assert c.in_corso == 1


def test_etichetta_settimana_a_cavallo_di_mese_e_anno():
    c = cal.costruisci_calendario([
        _p(1, None, _utc(2026, 10, 29, 12)), _p(2, None, _utc(2026, 12, 29, 12)),
    ])
    assert c.turni[0].etichetta == "Settimana dal 26 ottobre al 1 novembre 2026"
    assert c.turni[1].etichetta == "Settimana dal 28 dicembre 2026 al 3 gennaio 2027"


# ---------------------------------------------------------------- caricamento dal DB

def _prepara(sessione_db, *, senza_giornate=False):
    with sessione_db() as s:
        popola(s)
        # un subentrato a 0 minuti ammonito dalla panchina e un rosso, nella partita 6
        s.add(Giocatore(id=500, nome="Panchinaro", ruolo="M"))
        s.flush()
        s.add(Presenza(partita_id=6, giocatore_id=500, squadra_id=CASA, minuti=0, gialli=1, rossi=1))
        s.add(Presenza(partita_id=5, giocatore_id=500, squadra_id=CASA, minuti=1, gialli=1))
        if senza_giornate:
            for p in s.query(Partita):
                p.giornata = None


def test_righe_turno_giocate_con_risultato_arbitro_e_cartellini(sessione_db):
    _prepara(sessione_db)
    with sessione_db() as s:
        calendario = cal.carica_calendario(s, 135)
        assert [t.chiave for t in calendario.turni] == [1, 2, 3, 4, 5, 6, 7]
        assert calendario.turni[calendario.in_corso].chiave == 7
        righe = {r.id: r for r in cal.righe_turno(s, calendario.turni[5].ids)}
        r = righe[6]
        assert r.finita and (r.gol_casa, r.gol_trasferta) == (1, 1) and r.arbitro == "Rossi"
        # 4 gialli dei titolari + 1 dalla panchina; 1 rosso
        assert (r.gialli, r.rossi) == (5, 1)
        r5 = cal.righe_turno(s, calendario.turni[4].ids)[0]
        assert (r5.gialli, r5.rossi) == (1, 0)  # il subentrato di 1 minuto conta
        futura = cal.righe_turno(s, calendario.turni[6].ids)[0]
        assert not futura.finita and futura.gialli is None and futura.formazioni == "ufficiali"


def test_statistiche_non_scaricate_cartellini_non_disponibili(sessione_db):
    _prepara(sessione_db)
    with sessione_db() as s:
        s.get(Partita, 6).statistiche_scaricate = False
        s.flush()
        (r,) = cal.righe_turno(s, (6,))
        assert r.finita and r.gialli is None and r.rossi is None
        assert "Cartellini non ancora disponibili" in stile.scheda_partita(r)


def test_righe_turno_poche_query_per_qualsiasi_numero_di_partite(sessione_db):
    from sqlalchemy import event

    _prepara(sessione_db)
    with sessione_db() as s:
        istruzioni = []
        event.listen(s.get_bind(), "before_cursor_execute",
                     lambda *a, **k: istruzioni.append(a[2]))
        cal.righe_turno(s, (1,))
        una = len(istruzioni)
        istruzioni.clear()
        cal.righe_turno(s, (1, 2, 3, 4, 5, 6))
        assert len(istruzioni) == una


class _Risultato:
    def __init__(self, righe):
        self._righe = righe

    def all(self):
        return self._righe


class _SessioneDecimal:
    def __init__(self, righe):
        self._righe = righe

    def execute(self, _):
        return _Risultato(self._righe)


def test_cartellini_da_decimal_sono_int():
    s = _SessioneDecimal([(6, Decimal("5"), Decimal("1")), (7, None, None)])
    r = componenti.cartellini_partite(s, [6, 7])
    assert r == {6: (5, 1), 7: (0, 0)}
    assert all(type(v) is int for coppia in r.values() for v in coppia)
    assert componenti.cartellini_partite(s, []) == {}


# ---------------------------------------------------------------- scheda

def _riga(**kw):
    base = dict(
        id=1, quando="", giornata=3, casa="Casa <b>FC</b>", trasferta="Trasf", arbitro="Rossi",
        calda=False, formazioni="ufficiali", ora="20:45", data_utc=_utc(2026, 11, 8, 19, 45),
        campionato="Serie A", finita=True, stato="FT", gol_casa=2, gol_trasferta=0,
        gialli=1, rossi=0,
    )
    base.update(kw)
    return componenti.RigaPartita(**base)


def test_scheda_giocata_risultato_arbitro_e_cartellini():
    html = stile.scheda_partita(_riga())
    assert '<span class="cr-gol">2</span>' in html and '<span class="cr-gol">0</span>' in html
    assert "Arbitro: Rossi" in html
    assert "🟨 1 giallo" in html and "🟥 0 rossi" in html
    assert "Formazioni" not in html
    assert "<b>FC</b>" not in html and "&lt;b&gt;FC&lt;/b&gt;" in html


def test_scheda_giocata_plurali_e_arbitro_mancante():
    html = stile.scheda_partita(_riga(gialli=5, rossi=2, arbitro=None))
    assert "🟨 5 gialli" in html and "🟥 2 rossi" in html and "Arbitro non indicato" in html


def test_scheda_da_giocare_come_prima():
    html = stile.scheda_partita(_riga(finita=False, stato="NS", gol_casa=None, gol_trasferta=None,
                                      gialli=None, rossi=None, arbitro=None, formazioni="probabili"))
    assert "cr-gol" not in html and "Arbitro da designare" in html and "Formazioni probabili" in html


def test_scheda_rinviata():
    html = stile.scheda_partita(_riga(finita=False, stato="PST", gialli=None, rossi=None))
    assert "Rinviata" in html


# ---------------------------------------------------------------- pagina

def _schede(at):
    return [m.value for m in at.markdown if 'class="cr-partita"' in m.value]


def test_si_apre_sulla_giornata_in_corso(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CALENDARIO)
    assert not at.exception
    t = visibile(at)
    assert "Giornata 7" in t and "1 partita" in t and "giocat" not in t
    (scheda,) = _schede(at)
    assert "Casa FC" in scheda and "Formazioni ufficiali" in scheda and "Arbitro: Rossi" in scheda
    assert at.button(key="calendario_successivo").disabled
    assert not at.button(key="calendario_precedente").disabled
    assert not [b for b in at.button if b.key == "calendario_in_corso"]


def test_frecce_giornata_precedente_con_risultato_e_ritorno(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CALENDARIO)
    at.button(key="calendario_precedente").click().run()
    assert not at.exception
    assert "Giornata 6" in visibile(at)
    (scheda,) = _schede(at)
    assert '<span class="cr-gol">1</span>' in scheda and "Arbitro: Rossi" in scheda
    assert "🟨 5 gialli" in scheda and "🟥 1 rosso" in scheda  # compreso il giallo della panchina
    assert "1 partita · 1 giocata" in visibile(at)
    # torna alla giornata in corso con il pulsante dedicato, poi indietro di due con le frecce
    at.button(key="calendario_in_corso").click().run()
    assert "Giornata 7" in visibile(at)
    at.button(key="calendario_precedente").click().run()
    at.button(key="calendario_precedente").click().run()
    assert "Giornata 5" in visibile(at)
    at.button(key="calendario_successivo").click().run()
    assert "Giornata 6" in visibile(at)


def test_prima_giornata_ha_la_freccia_indietro_disattivata(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CALENDARIO)
    for _ in range(6):
        at.button(key="calendario_precedente").click().run()
    assert "Giornata 1" in visibile(at)
    assert at.button(key="calendario_precedente").disabled
    assert not at.button(key="calendario_successivo").disabled


def test_partite_divise_per_giorno_come_nella_pagina_partite(sessione_db):
    _prepara(sessione_db)
    with sessione_db() as s:
        s.add(Partita(id=301, data_utc=PARTITA_DATA_DOPO, competizione_id=135, stagione=2026,
                      giornata=7, casa_id=TRASF, trasferta_id=CASA, stato="NS"))
    at = avvia(PAGINA_CALENDARIO)
    # il titolo puo' iniziare con "Oggi · " o "Domani · " secondo la data in cui gira il test
    titoli = [h.value.split(" · ")[-1] for h in at.subheader]
    assert titoli == ["domenica 8 novembre 2026", "lunedì 9 novembre 2026"]
    assert len(_schede(at)) == 2


def test_link_al_dettaglio_di_ogni_partita(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CALENDARIO)
    assert not at.exception
    assert any("Apri dettaglio" in (getattr(e, "label", "") or "") for e in at.get("page_link"))


def test_liga_senza_partite_non_manda_in_errore(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CALENDARIO)
    scegli_campionato(at, "Liga")
    assert not at.exception
    assert "Nessuna partita di Liga" in visibile(at)


def test_liga_con_la_sua_giornata(sessione_db):
    _prepara(sessione_db)
    with sessione_db() as s:
        s.add_all([Squadra(id=601, nome="Real Liga"), Squadra(id=602, nome="Barca Liga")])
        s.flush()
        s.add(Partita(id=900, data_utc=datetime.now(timezone.utc) + timedelta(days=3),
                      competizione_id=140, stagione=2026, giornata=11, casa_id=601,
                      trasferta_id=602, stato="NS"))
    at = avvia(PAGINA_CALENDARIO)
    assert "Real Liga" not in visibile(at)
    scegli_campionato(at, "Liga")
    assert not at.exception
    assert "Giornata 11" in visibile(at) and "Real Liga" in visibile(at)
    # tornando alla Serie A resta la sua giornata
    scegli_campionato(at, "Serie A")
    assert "Giornata 7" in visibile(at)


def test_tutti_mostra_la_serie_a(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_CALENDARIO)
    scegli_campionato(at, "Tutti")
    assert not at.exception
    assert "Giornata 7" in visibile(at) and "un campionato alla volta" in visibile(at)


def test_senza_giornate_si_naviga_per_settimana(sessione_db):
    _prepara(sessione_db, senza_giornate=True)
    at = avvia(PAGINA_CALENDARIO)
    assert not at.exception
    t = visibile(at)
    assert "Settimana dal 2 al 8 novembre 2026" in t and "Giornata 7" not in t
    assert len(_schede(at)) == 1
    at.button(key="calendario_precedente").click().run()
    assert not at.exception
    assert "Settimana dal 12 al 18 ottobre 2026" in visibile(at)
    at.button(key="calendario_in_corso").click().run()
    assert "Settimana dal 2 al 8 novembre 2026" in visibile(at)


def test_database_vuoto_nessun_errore(sessione_db):
    at = avvia(PAGINA_CALENDARIO)
    assert not at.exception
    assert "Nessuna partita di Serie A" in visibile(at)


def test_nomi_squadra_con_html_escapati(sessione_db):
    _prepara(sessione_db)
    with sessione_db() as s:
        s.get(Squadra, CASA).nome = "<script>alert(1)</script>"
    at = avvia(PAGINA_CALENDARIO)
    html = "\n".join(m.value for m in at.markdown)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_menu_in_ordine():
    sorgente = (RADICE / "app" / "Partite.py").read_text(encoding="utf-8")
    titoli = re.findall(r'st\.Page\([^)]*title="([^"]+)"[^)]*\)', sorgente)
    visibili = [
        t for t, riga in zip(titoli, re.findall(r"st\.Page\([^)]*\)", sorgente))
        if 'visibility="hidden"' not in riga
    ]
    assert visibili == ["Home", "Partite", "Partite calde", "Classifica", "Calendario", "Arbitri", "Cerca", "Giocate", "Impostazioni"]
