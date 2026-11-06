"""Classifica dei campionati: calcolo dai risultati, forma, zone, cartellini a partita
(panchina compresa), query raggruppate, Decimal di Postgres, HTML e pagina."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import componenti_classifica as cc
import stile
from ayuda_app import (  # noqa: F401
    PAGINA_CLASSIFICA, avvia, scegli_campionato, sessione_db, url_db, visibile,
)
from sqlalchemy import event

from ammonizioni.db.modelli import Partita, Presenza, Squadra

BASE = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
SQUADRE = {1: ("Alfa", None), 2: ("Beta", None), 3: ("Gamma", None), 4: ("Delta", None)}


def _r(giorno, casa, trasf, gc, gt):
    return (BASE + timedelta(days=giorno), casa, trasf, gc, gt)


# ---------------------------------------------------------------- calcolo (logica pura)

def test_punti_giocate_vnp_gol_e_ordine():
    risultati = [_r(0, 1, 2, 2, 0), _r(1, 3, 4, 1, 1), _r(2, 2, 3, 0, 3), _r(3, 4, 1, 1, 1)]
    cl = cc.calcola_classifica(135, risultati, SQUADRE)
    assert [r.nome for r in cl.righe] == ["Gamma", "Alfa", "Delta", "Beta"]
    gamma, alfa = cl.righe[0], cl.righe[1]
    assert (gamma.punti, gamma.giocate, gamma.vinte, gamma.pari, gamma.perse) == (4, 2, 1, 1, 0)
    assert (gamma.gol_fatti, gamma.gol_subiti, gamma.differenza) == (4, 1, 3)
    assert (alfa.punti, alfa.differenza) == (4, 2)  # stessi punti: conta la differenza reti
    assert [r.posizione for r in cl.righe] == [1, 2, 3, 4]


def test_parita_differenza_poi_gol_fatti_poi_nome():
    # tutte a 3 punti e differenza 0: prima chi ha fatto più gol, poi il nome
    risultati = [_r(0, 1, 2, 3, 2), _r(1, 2, 1, 3, 2), _r(2, 3, 4, 1, 0), _r(3, 4, 3, 1, 0)]
    cl = cc.calcola_classifica(135, risultati, SQUADRE)
    assert [r.nome for r in cl.righe] == ["Alfa", "Beta", "Delta", "Gamma"]
    assert "scontri diretti" in cc.NOTA_CRITERI and "non sono applicati" in cc.NOTA_CRITERI


def test_squadra_senza_partite_compare_a_zero():
    cl = cc.calcola_classifica(135, [_r(0, 1, 2, 1, 0)], SQUADRE)
    delta = next(r for r in cl.righe if r.nome == "Delta")
    assert delta.giocate == 0 and delta.punti == 0 and delta.forma == ()
    assert delta.gialli_partita is None and cc.media(delta.gialli_partita) == "–"


def test_forma_ultime_5_dalla_meno_recente_con_descrizione():
    risultati = [_r(g, 1, 2, gc, gt) for g, (gc, gt) in enumerate(
        [(0, 1), (1, 0), (2, 2), (3, 0), (0, 0), (1, 2)]
    )]
    cl = cc.calcola_classifica(135, list(reversed(risultati)), SQUADRE)  # ordine di data
    alfa = next(r for r in cl.righe if r.nome == "Alfa")
    assert [e for e, _ in alfa.forma] == ["V", "N", "V", "N", "P"]
    assert alfa.forma[-1][1] == "Sconfitta 1–2 con Beta (in casa)"
    beta = next(r for r in cl.righe if r.nome == "Beta")
    assert beta.forma[-1] == ("V", "Vittoria 2–1 con Alfa (in trasferta)")


def test_cartellini_a_partita():
    cl = cc.calcola_classifica(135, [_r(0, 1, 2, 0, 0)], SQUADRE, {1: (7, 1, 2)})
    alfa = next(r for r in cl.righe if r.nome == "Alfa")
    assert alfa.gialli_partita == 3.5 and alfa.rossi_partita == 0.5
    assert cc.media(alfa.gialli_partita) == "3,50"


def test_zone_dalla_configurazione_e_retrocessione():
    assert [cc.zona_di(p, 20, 135) for p in (1, 4, 5, 6, 7, 8, 17, 18, 20)] == [
        "champions", "champions", "europa", "europa", "conference", None, None,
        "retrocessione", "retrocessione",
    ]
    # poche squadre: le zone europee hanno la precedenza
    assert [cc.zona_di(p, 8, 140) for p in range(1, 9)] == [
        "champions"] * 4 + ["europa"] * 2 + ["conference", "retrocessione"]
    squadre = {i: (f"S{i:02d}", None) for i in range(1, 21)}
    cl = cc.calcola_classifica(135, [], squadre)
    assert cl.zone == ("champions", "europa", "conference", "retrocessione")


def test_differenza_con_il_segno():
    assert (cc.differenza(3), cc.differenza(0), cc.differenza(-2)) == ("+3", "0", "-2")


# ---------------------------------------------------------------- dal DB

def _squadre(s, ids=range(1, 5), campionato=135):
    for i in ids:
        s.add(Squadra(id=i, nome=f"Squadra {i}", logo_url=f"https://a.espncdn.com/{i}.png"))
    s.flush()


def _partita(s, pid, giorno, casa, trasf, gc=None, gt=None, stato="FT", competizione=135,
             statistiche=True, stagione=2026):
    s.add(Partita(id=pid, data_utc=BASE + timedelta(days=giorno), competizione_id=competizione,
                  stagione=stagione, casa_id=casa, trasferta_id=trasf, gol_casa=gc,
                  gol_trasferta=gt, stato=stato, statistiche_scaricate=statistiche))
    s.flush()


def _presenza(s, pid, gid, squadra, gialli=0, rossi=0, minuti=90):
    from ammonizioni.db.modelli import Giocatore

    if s.get(Giocatore, gid) is None:
        s.add(Giocatore(id=gid, nome=f"G{gid}"))
        s.flush()
    s.add(Presenza(partita_id=pid, giocatore_id=gid, squadra_id=squadra, gialli=gialli,
                   rossi=rossi, minuti=minuti))


def test_dal_db_solo_partite_finite_della_stagione_e_gialli_dalla_panchina(sessione):
    _squadre(sessione)
    _partita(sessione, 1, 0, 1, 2, 2, 1)
    _partita(sessione, 2, 1, 3, 4, 0, 0)
    _partita(sessione, 3, 9, 1, 3, stato="NS")  # futura: non conta
    _partita(sessione, 4, 2, 1, 4, 5, 0, stagione=2025)  # altra stagione
    _partita(sessione, 5, 3, 1, 2, 3, 0, competizione=137)  # coppa: non conta
    _presenza(sessione, 1, 10, 1, gialli=1)
    _presenza(sessione, 1, 11, 1, gialli=1, minuti=0)  # giallo dalla panchina: conta
    _presenza(sessione, 1, 12, 2, rossi=1, minuti=1)
    _presenza(sessione, 5, 10, 1, gialli=1)  # coppa: non conta
    sessione.flush()
    (cl,) = cc.carica_classifiche(sessione, (135,), 2026)
    assert cl.nome == "Serie A" and len(cl.righe) == 4
    uno = cl.righe[0]
    assert (uno.squadra_id, uno.punti, uno.giocate) == (1, 3, 1)
    assert (uno.gialli, uno.rossi, uno.partite_cartellini) == (2, 0, 1)
    assert uno.logo == "https://a.espncdn.com/1.png"
    due = next(r for r in cl.righe if r.squadra_id == 2)
    assert (due.gialli, due.rossi, due.partite_cartellini) == (0, 1, 1)


def test_dal_db_piu_campionati_nell_ordine_chiesto(sessione):
    _squadre(sessione)
    _squadre(sessione, ids=range(5, 7))
    _partita(sessione, 1, 0, 1, 2, 1, 0)
    _partita(sessione, 2, 0, 5, 6, 0, 2, competizione=140)
    a, b = cc.carica_classifiche(sessione, (135, 140), 2026)
    assert (a.nome, b.nome) == ("Serie A", "Liga")
    assert {r.squadra_id for r in a.righe} == {1, 2}
    assert [r.squadra_id for r in b.righe] == [6, 5]
    assert cc.carica_classifiche(sessione, (), 2026) == ()


def test_senza_immagini_niente_stemmi(sessione):
    import componenti

    _squadre(sessione)
    _partita(sessione, 1, 0, 1, 2, 1, 0)
    componenti.imposta_immagini(sessione, False)
    (cl,) = cc.carica_classifiche(sessione, (135,), 2026)
    assert all(r.logo is None for r in cl.righe)


def test_query_raggruppate_non_una_per_squadra(sessione):
    _squadre(sessione, ids=range(1, 21))
    for i in range(40):
        _partita(sessione, 100 + i, i, 1 + i % 20, 1 + (i + 7) % 20, i % 3, i % 2)
        _presenza(sessione, 100 + i, 1000 + i, 1 + i % 20, gialli=1)
    engine = sessione.get_bind()
    conteggi = []

    def conta(*_):
        conteggi.append(1)

    event.listen(engine, "before_cursor_execute", conta)
    try:
        cc.carica_classifiche(sessione, (135, 140), 2026)
    finally:
        event.remove(engine, "before_cursor_execute", conta)
    assert len(conteggi) <= 5


def test_aggregati_decimal_di_postgres_diventano_int():
    class Risultato:
        def all(self):
            return [(135, 1, Decimal("7"), Decimal("1"), Decimal("3"))]

    class SessioneDecimal:
        def execute(self, _):
            return Risultato()

    valori = cc._cartellini(SessioneDecimal(), (135,), 2026)
    assert valori == {(135, 1): (7, 1, 3)}
    assert all(type(v) is int for v in valori[(135, 1)])


# ---------------------------------------------------------------- HTML

def _riga(**campi):
    base = dict(
        posizione=1, squadra_id=9, nome="Inter", logo=None, punti=10, giocate=4, vinte=3,
        pari=1, perse=0, gol_fatti=8, gol_subiti=2,
        forma=(("V", "Vittoria 2–0 con Milan (in casa)"), ("N", "Pareggio 1–1"), ("P", "Sconfitta")),
        gialli=9, rossi=1, partite_cartellini=4, zona="champions",
    )
    base.update(campi)
    return cc.RigaTabella(**base)


def test_riga_classifica_con_zona_stemma_forma_e_cartellini():
    h = stile.riga_classifica(_riga())
    assert "cr-cl-zona--champions" in h and ">IN</span>" in h and "Inter" in h
    assert h.count("cr-forma--V") == 1 and "cr-forma--N" in h and "cr-forma--P" in h
    assert 'title="Vittoria 2–0 con Milan (in casa)"' in h
    assert ">+6<" in h and ">2,25<" in h and ">0,25<" in h  # DR, gialli e rossi a partita
    assert "<details" in h  # su telefono le altre colonne in una riga espandibile
    assert "\n" not in h


def test_riga_classifica_fa_l_escape():
    h = stile.riga_classifica(_riga(nome="<b>Brutta</b>", forma=(("V", "<i>x</i>"),)))
    assert "<b>Brutta" not in h and "&lt;b&gt;Brutta" in h and "<i>x" not in h


def test_testa_e_legenda():
    testa = stile.testa_classifica()
    for colonna in ("Pt", "G", "V", "N", "P", "GF", "GS", "DR", "Forma"):
        assert f">{colonna}<" in testa
    assert "a partita" in testa
    legenda = stile.legenda_zone(("champions", "retrocessione"))
    assert "Champions League" in legenda and "Retrocessione" in legenda
    assert "Europa League" not in legenda


# ---------------------------------------------------------------- pagina

def _dati_pagina(s):
    s.add_all([Squadra(id=1, nome="Inter"), Squadra(id=2, nome="Milan"),
               Squadra(id=3, nome="<b>Brutta</b>"), Squadra(id=5, nome="Real Madrid"),
               Squadra(id=6, nome="FC Barcelona")])
    s.flush()
    _partita(s, 1, 0, 1, 2, 2, 0)
    _partita(s, 2, 1, 2, 3, 1, 1)
    _partita(s, 3, 0, 5, 6, 0, 1, competizione=140)
    _presenza(s, 1, 10, 1, gialli=1, minuti=0)


def test_pagina_classifica_serie_a_predefinita(sessione_db):
    with sessione_db() as s:
        _dati_pagina(s)
    at = avvia(PAGINA_CLASSIFICA)
    assert not at.exception
    testo = visibile(at)
    assert "Classifica" in testo and "Inter" in testo and "Milan" in testo
    assert "Real Madrid" not in testo
    assert "&lt;b&gt;Brutta&lt;/b&gt;" in testo and "<b>Brutta</b>" not in testo
    assert "scontri diretti" in testo
    # clic su una squadra: pagina Cerca della squadra
    link = [p for p in at.get("page_link") if p.proto.label == "Inter"]
    assert link and "Cerca" in link[0].proto.page and link[0].proto.query_string == "squadra=1"


def test_pagina_classifica_liga_e_tutti(sessione_db):
    with sessione_db() as s:
        _dati_pagina(s)
    at = scegli_campionato(avvia(PAGINA_CLASSIFICA), "Liga")
    testo = visibile(at)
    assert "Real Madrid" in testo and "Inter" not in testo
    at = scegli_campionato(at, "Tutti")
    testo = visibile(at)
    assert "Real Madrid" in testo and "Inter" in testo
    assert testo.index("Serie A") < testo.index("Liga")


def test_pagina_classifica_senza_partite(sessione_db):
    with sessione_db():
        pass
    at = avvia(PAGINA_CLASSIFICA)
    assert not at.exception
    assert "Nessuna partita" in visibile(at)
