"""Home: riquadri, classifica degli ammoniti (ogni cartellino conta), grafici, biografie,
e la pagina nell'app (pagina iniziale dopo l'accesso)."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from ayuda_app import (  # noqa: F401
    PAGINA_APP, PAGINA_HOME, RADICE, avvia, scegli_campionato, sessione_db, url_db, visibile,
)
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola, popola_panchina
from streamlit.testing.v1 import AppTest

import componenti
import componenti_home as home
import grafici
import stile
from ammonizioni.db.modelli import Giocata, Giocatore, Partita, Presenza, Squadra

ADESSO = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)


def _riga(gid, nome="X", gialli=0, rossi=0, minuti=900, falli=10, presenze=10, squadra="S"):
    return home.RigaClassifica(
        giocatore_id=gid, nome=nome, squadra=squadra, ruolo="", presenze=presenze,
        minuti=minuti, gialli=gialli, rossi=rossi, falli=falli,
    )


class _SommeDecimal:
    """Come Postgres: le colonne SUM arrivano come Decimal."""

    def __init__(self, s):
        self._s = s

    def execute(self, *a, **k):
        risultato = self._s.execute(*a, **k)
        righe = risultato.all()

        class R:
            def all(_):
                return [
                    tuple(Decimal(v) if n.startswith("sum") and v is not None else v
                          for n, v in zip(r._fields, r))
                    for r in righe
                ]

            def scalars(_):
                return iter([r[0] for r in righe])

        return R()


# ---------------------------------------------------------------- classifica

def test_ogni_cartellino_conta_panchina_e_subentrati(sessione_db):
    with sessione_db() as s:
        popola(s)
        popola_panchina(s)
    with sessione_db() as s:
        righe = {r.giocatore_id: r for r in home.classifica_ammoniti(s, (135,))}
    # il 25 è ammonito dalla panchina nella partita 3 (0 minuti): conta
    assert righe[25].gialli == 1 and righe[25].presenze == 3 and righe[25].minuti == 60
    # chi non è mai entrato: nessuna presenza e niente per 90'
    assert righe[16].presenze == 0 and righe[16].gialli_90 is None
    # i titolari pari prendono un giallo nelle partite pari: 3 gialli in 6 partite
    assert righe[12].gialli == 3 and righe[12].squadra == "Casa FC"
    assert righe[12].gialli_90 == pytest.approx(3 * 90 / 540)
    assert righe[12].falli_90 == pytest.approx(2.0)
    with sessione_db() as s:
        ordine = [r.gialli for r in home.classifica_ammoniti(s, (135,))]
    assert ordine == sorted(ordine, reverse=True) and ordine[0] == 3


def test_classifica_con_somme_decimal(sessione_db):
    with sessione_db() as s:
        popola(s)
        popola_panchina(s)
        righe = home.classifica_ammoniti(_SommeDecimal(s), (135,))
        giornate = home.gialli_per_giornata(_SommeDecimal(s), (135,))
        squadre = home.media_gialli_squadre(_SommeDecimal(s), (135,))
    for r in righe:
        for v in (r.presenze, r.minuti, r.gialli, r.rossi, r.falli):
            assert type(v) is int
    assert all(type(g["Gialli"]) is int for g in giornate)
    assert all(type(q["Gialli"]) is int and type(q["Media"]) is float for q in squadre)


def test_squadra_attuale_e_l_ultima(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.add(Squadra(id=3, nome="Nuova FC"))
        s.add(Partita(id=50, data_utc=datetime(2026, 10, 30, tzinfo=timezone.utc), competizione_id=135,
                      stagione=2026, giornata=8, casa_id=3, trasferta_id=TRASF, stato="FT"))
        s.flush()
        s.add(Presenza(partita_id=50, giocatore_id=12, squadra_id=3, minuti=90, gialli=1))
    with sessione_db() as s:
        righe = {r.giocatore_id: r for r in home.classifica_ammoniti(s, (135,))}
    assert righe[12].squadra == "Nuova FC" and righe[12].gialli == 4


def test_filtra_e_ordina():
    righe = [_riga(1, "Hakan Çalhanoğlu", gialli=2, squadra="Inter"),
             _riga(2, "Marco Rossi", gialli=5, rossi=1, minuti=0, presenze=0),
             _riga(3, "Luca Bianchi", gialli=1, falli=40, squadra="Milan")]
    assert [r.giocatore_id for r in home.filtra_e_ordina(righe)] == [2, 1, 3]
    assert [r.giocatore_id for r in home.filtra_e_ordina(righe, "calhanoglu")] == [1]
    assert [r.giocatore_id for r in home.filtra_e_ordina(righe, "MILAN")] == [3]
    assert [r.giocatore_id for r in home.filtra_e_ordina(righe, "", "Falli per 90'")] == [3, 1, 2]
    assert home.filtra_e_ordina(righe, "", "Rossi")[0].giocatore_id == 2


def test_righe_tabella():
    (r,) = home.righe_tabella([_riga(1, "A", gialli=3, minuti=270)])
    assert r["#"] == 1 and r["Gialli"] == 3 and r["Gialli 90'"] == 1.0
    (r,) = home.righe_tabella([_riga(1, "A", gialli=1, minuti=0)])
    assert r["Gialli 90'"] is None


# ---------------------------------------------------------------- grafici

def test_in_ritardo():
    righe = [_riga(i, minuti=900, falli=20, gialli=2) for i in range(1, 9)]
    righe.append(_riga(50, "Picchiatore", minuti=900, falli=45, gialli=1))
    righe.append(_riga(51, "Picchiatore ammonito", minuti=900, falli=45, gialli=6))
    righe.append(_riga(52, "Pochi minuti", minuti=100, falli=30, gialli=0))
    assert home.in_ritardo(righe) == {50}
    dati = home.dati_dispersione(righe)
    assert {d["Giocatore"] for d in dati if d["Gruppo"] == "In ritardo"} == {"Picchiatore"}
    assert "Pochi minuti" not in {d["Giocatore"] for d in dati}
    assert home.in_ritardo([]) == set()


def test_dati_primi_solo_ammoniti():
    righe = [_riga(i, f"G{i}", gialli=20 - i) for i in range(20)]
    assert len(home.dati_primi(righe)) == 15
    assert home.dati_primi([_riga(1, gialli=0)]) == []


def test_gialli_per_giornata_e_per_squadra(sessione_db):
    with sessione_db() as s:
        popola(s)
        popola_panchina(s)
    with sessione_db() as s:
        giornate = home.gialli_per_giornata(s, (135,))
        squadre = home.media_gialli_squadre(s, (135,))
    per_g = {g["Giornata"]: g["Gialli"] for g in giornate}
    assert per_g[3] == 1  # solo il giallo dalla panchina
    assert per_g[2] == 4  # i 4 titolari pari
    assert {q["Squadra"] for q in squadre} == {"Casa FC", "Trasferta FC"}
    assert all(q["Partite"] == 6 for q in squadre)


@pytest.mark.parametrize("tema", ["scuro", "chiaro"])
def test_grafici_con_i_colori_del_tema(tema):
    p = stile.PALETTE[tema]
    righe = [_riga(i, f"G{i}", gialli=i, falli=10 + i) for i in range(1, 6)]
    spec = grafici.barre_primi(home.dati_primi(righe), tema).to_dict()
    testo = str(spec)
    assert p["giallo"] in testo and "transparent" in testo and p["testo2"] in testo
    assert p["rosso"] in str(grafici.dispersione(home.dati_dispersione(righe), tema).to_dict())
    giornate = [{"Campionato": "Serie A", "Giornata": 1, "Gialli": 4, "Media a partita": 2.0},
                {"Campionato": "Liga", "Giornata": 1, "Gialli": 5, "Media a partita": 2.5}]
    spec = str(grafici.per_giornata(giornate, tema).to_dict())
    assert grafici.BLU[tema] in spec
    spec = str(grafici.per_squadra([{"Squadra": "A", "Gialli": 4, "Partite": 2, "Media": 2.0}], tema).to_dict())
    assert p["giallo"] in spec


# ---------------------------------------------------------------- riquadri

def _riga_partita(pid, quando, attesi=None):
    return componenti.RigaPartita(
        id=pid, quando="", giornata=1, casa="A", trasferta="B", arbitro=None, calda=True,
        formazioni="probabili", data_utc=quando, attesi=attesi,
    )


def test_oggi_e_domani_ora_di_roma():
    righe = [
        _riga_partita(1, datetime(2026, 11, 6, 19, 45, tzinfo=timezone.utc)),
        _riga_partita(2, datetime(2026, 11, 7, 22, 30, tzinfo=timezone.utc)),  # 23:30 sabato
        _riga_partita(3, datetime(2026, 11, 7, 23, 30, tzinfo=timezone.utc)),  # 00:30 domenica
    ]
    assert [r.id for r in home.oggi_e_domani(righe, ADESSO)] == [1, 2]


def test_piu_calda():
    a = _riga_partita(1, ADESSO + timedelta(days=1), attesi=5.0)
    b = _riga_partita(2, ADESSO + timedelta(days=2), attesi=6.1)
    c = _riga_partita(3, ADESSO + timedelta(days=3))
    assert home.piu_calda([a, b, c]).id == 2
    assert home.piu_calda([]) is None


def test_piu_a_rischio(sessione_db):
    with sessione_db() as s:
        popola(s)
    with sessione_db() as s:
        r = home.piu_a_rischio(s, [PARTITA_FUTURA, 99999])
    assert r is not None and r.partita_id == PARTITA_FUTURA
    assert r.partita == "Casa FC – Trasferta FC" and 0 < r.probabilita < 1
    with sessione_db() as s:
        assert home.piu_a_rischio(s, []) is None


def test_riepilogo_giocate(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.add_all([
            Giocata(data=date(2026, 9, 8), partita_id=1, giocatore_id=12, fonte="io", quota=3.0, puntata=10, esito="vinta"),
            Giocata(data=date(2026, 9, 15), partita_id=2, giocatore_id=12, fonte="io", quota=2.0, puntata=10, esito="persa"),
            Giocata(data=date(2026, 9, 22), partita_id=3, giocatore_id=12, fonte="io", quota=2.0, puntata=10, esito="in_attesa"),
        ])
    with sessione_db() as s:
        r = home.riepilogo_giocate(s, (135,))
    assert (r.chiuse, r.vinte) == (2, 1)
    assert r.profitto == pytest.approx(10.0) and r.rendimento == pytest.approx(0.5)
    assert len(r.ultime) == 3
    with sessione_db() as s:
        assert home.riepilogo_giocate(s, (140,)).rendimento is None


# ---------------------------------------------------------------- biografie

def test_eta():
    assert home.eta(date(1994, 3, 17), date(2026, 11, 6)) == 32
    assert home.eta(date(1994, 11, 7), date(2026, 11, 6)) == 31
    assert home.eta(None, date(2026, 11, 6)) is None


def test_biografie_nell_ordine_della_classifica(sessione_db):
    with sessione_db() as s:
        popola(s)
        g = s.get(Giocatore, 14)
        g.data_nascita, g.nazionalita, g.altezza_cm = date(2000, 1, 1), "Italia", 185
        g = s.get(Giocatore, 12)
        g.wiki_estratto, g.wiki_url = "Terzino di prova.", "https://it.wikipedia.org/wiki/T"
    with sessione_db() as s:
        righe = home.classifica_ammoniti(s, (135,))
        bio = home.biografie(s, home.candidati_bio(righe), date(2026, 11, 6))
    # 3 gialli a testa: a parità di tutto, per nome ("Punta Casa" prima di "Terzino Casa")
    assert [b.giocatore_id for b in bio] == [14, 12]
    assert bio[1].wiki_url == "https://it.wikipedia.org/wiki/T" and bio[1].squadra == "Casa FC"
    assert bio[0].eta == 26 and bio[0].wiki_url is None


def test_scheda_bio_con_fonte_e_escape():
    b = home.Biografia(1, "<Nome>", "Inter", 32, "Italia", 193, "Portiere", "Testo <b>x</b>",
                       "https://it.wikipedia.org/wiki/Ivan_Provedel")
    html = stile.scheda_bio(b)
    assert "&lt;Nome&gt;" in html and "Testo &lt;b&gt;x&lt;/b&gt;" in html
    assert "32 anni" in html and "1,93 m" in html and "Inter · Portiere" in html
    assert 'Fonte: <a href="https://it.wikipedia.org/wiki/Ivan_Provedel"' in html and "CC BY-SA" in html
    # un link che non è di Wikipedia non si mostra
    altro = home.Biografia(1, "N", "", None, None, None, None, "T", "javascript:alert(1)")
    assert "href" not in stile.scheda_bio(altro)


def test_riquadro_home_escape():
    html = stile.riquadro_home("<e>", "<t>", "<s>", righe=["<r>"], badges=[stile.badge("ok")])
    assert "<e>" not in html and "&lt;t&gt;" in html and "&lt;r&gt;" in html and "cr-badge" in html


# ---------------------------------------------------------------- nella pagina

def _prepara(sessione_db):
    with sessione_db() as s:
        popola(s)
        popola_panchina(s)
        s.get(Partita, PARTITA_FUTURA).data_utc = datetime.now(timezone.utc) + timedelta(hours=26)
        g = s.get(Giocatore, 12)
        g.wiki_estratto, g.wiki_url = "Terzino di prova.", "https://it.wikipedia.org/wiki/T"
        g.nazionalita = "Italia"


def test_home_e_la_pagina_iniziale(sessione_db):
    _prepara(sessione_db)
    at = AppTest.from_file(PAGINA_APP, default_timeout=30).run()
    assert not at.exception
    assert [t.value for t in at.title] == ["Home"]
    testo = (RADICE / "app" / "Partite.py").read_text(encoding="utf-8")
    assert testo.index('title="Home"') < testo.index('title="Partite"')
    assert 'title="Home", icon="🏠", default=True' in testo


def test_home_mostra_riquadri_classifica_grafici_e_bio(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_HOME)
    assert not at.exception
    t = visibile(at)
    assert "Oggi e domani" in t and "Casa FC – Trasferta FC" in t
    assert "Partita più calda" in t and "Più a rischio giallo" in t
    assert "Le tue giocate" in t and "Nessuna giocata chiusa" in t
    assert "Classifica degli ammoniti" in t
    assert len(at.dataframe) == 1
    tabella = at.dataframe[0].value
    assert tabella.iloc[0]["Gialli"] == 3
    assert "Mediano Riserva Trasf" in set(tabella["Giocatore"])  # il giallo dalla panchina
    assert "Profili dei più ammoniti" in t and "Terzino di prova." in t and "Fonte: <a" in t
    assert len(at.get("arrow_vega_lite_chart")) >= 1 or len(at.get("vega_lite_chart")) >= 1


def test_home_ricerca_nella_classifica(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_HOME)
    at.text_input(key="home_cerca").set_value("riserva").run()
    assert not at.exception
    assert set(at.dataframe[0].value["Giocatore"]) == {"Mediano Riserva Trasf", "Punta Riserva Casa"}
    at.text_input(key="home_cerca").set_value("nessuno così").run()
    assert "Nessun giocatore corrisponde" in visibile(at)


def test_home_clic_su_un_giocatore_apre_la_scheda(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_HOME)
    at.session_state["home_vai_giocatore"] = 25
    at.run()
    assert not at.exception
    assert "Mediano Riserva Trasf" in visibile(at)
    assert at.query_params.get("giocatore") == "25"


def test_home_liga_senza_dati(sessione_db):
    _prepara(sessione_db)
    at = avvia(PAGINA_HOME)
    scegli_campionato(at, "Liga")
    assert not at.exception
    t = visibile(at)
    assert "Nessuna presenza registrata" in t and "Nessuna partita" in t


@pytest.mark.parametrize("tema", ["scuro", "chiaro"])
def test_home_nei_due_temi(sessione_db, tema):
    _prepara(sessione_db)
    at = avvia(PAGINA_HOME, tema=tema)
    assert not at.exception
