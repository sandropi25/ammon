"""Pagina Arbitri e scheda arbitro: medie dai cartellini totali di partita (anche la stagione
2023, senza giocatori), campionato scelto, ordinamento, Decimal di Postgres, query
raggruppate, HTML con escape e link dalle schede partita e dal Dettaglio."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import ayuda_app  # noqa: F401  (aggiunge app/ a sys.path)
import componenti_arbitri as ca
import stile
from ayuda_app import (  # noqa: F401
    PAGINA_ARBITRI, PAGINA_DETTAGLIO, PAGINA_PARTITE, RADICE, avvia, scegli_campionato, sessione_db,
    url_db, visibile,
)
from db_prova import CASA, PARTITA_FUTURA, TRASF, popola
from sqlalchemy import event

from ammonizioni.caricamento.totali import riempi_da_presenze
from ammonizioni.db.modelli import Arbitro, Partita, Squadra

ADESSO = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def _partita_2023(s, pid, giorni, gialli, rossi, falli, arbitro=1, comp=135, stagione=2023):
    s.add(Partita(
        id=pid, data_utc=datetime(2023, 9, 1, tzinfo=timezone.utc) + timedelta(days=giorni),
        competizione_id=comp, stagione=stagione, giornata=giorni + 1,
        casa_id=CASA if giorni % 2 else TRASF, trasferta_id=TRASF if giorni % 2 else CASA,
        arbitro_id=arbitro, gol_casa=1, gol_trasferta=0, stato="FT", statistiche_scaricate=False,
        gialli_totali=gialli, rossi_totali=rossi, falli_totali=falli,
    ))
    s.flush()


def _scenario(s):
    """Rossi: 6 partite 2026 con presenze (12 gialli, 0 rossi, 96 falli) e 3 della 2023 solo
    con i totali (15 gialli, 1 rosso, falli 20 e 24 + uno sconosciuto). Un arbitro di Liga."""
    popola(s)
    riempi_da_presenze(s)
    _partita_2023(s, 900, 0, 5, 0, 20)
    _partita_2023(s, 901, 1, 7, 1, None)
    _partita_2023(s, 902, 2, 3, 0, 24)
    s.add(Arbitro(id=2, nome_normalizzato="140:ortega", nome_visualizzato="Pablo Ortega"))
    s.add(Squadra(id=50, nome="Real Madrid"))
    s.add(Squadra(id=51, nome="Barcelona"))
    s.flush()
    s.add(Partita(
        id=950, data_utc=datetime(2026, 10, 1, tzinfo=timezone.utc), competizione_id=140,
        stagione=2026, casa_id=50, trasferta_id=51, arbitro_id=2, stato="FT",
        gialli_totali=8, rossi_totali=2, falli_totali=30,
    ))
    s.flush()


# ---------------------------------------------------------------- calcolo

def test_elenco_serie_a_medie_dalle_partite_con_e_senza_giocatori(sessione):
    _scenario(sessione)
    elenco = ca.carica_elenco(sessione, (135,))
    assert [r.nome for r in elenco.righe] == ["Rossi"]
    t = elenco.righe[0].totale
    assert (t.partite, t.gialli, t.rossi, t.con_rosso) == (9, 27, 1, 1)
    assert t.gialli_media == 3.0 and round(t.rossi_media, 3) == 0.111
    assert t.falli == 140 and t.partite_falli == 8 and t.falli_media == 17.5
    assert round(t.percentuale_rosso, 1) == 11.1
    assert elenco.media_gialli_lega == 3.0


def test_elenco_campionato_scelto_e_tutti_ordinati_per_gialli(sessione):
    _scenario(sessione)
    assert [r.nome for r in ca.carica_elenco(sessione, (140,)).righe] == ["Pablo Ortega"]
    tutti = ca.carica_elenco(sessione, (135, 140))
    assert [r.nome for r in tutti.righe] == ["Pablo Ortega", "Rossi"]  # 8 gialli contro 3
    assert tutti.righe[0].campionati == (140,)
    assert [r.nome for r in ca.ordina(tutti.righe, "Partite arbitrate")] == ["Rossi", "Pablo Ortega"]
    assert [r.nome for r in ca.ordina(tutti.righe, "Nome")] == ["Pablo Ortega", "Rossi"]
    assert ca.carica_elenco(sessione, ()).righe == ()


def test_partite_senza_cartellini_noti_o_non_finite_non_contano(sessione):
    _scenario(sessione)
    sessione.get(Partita, 900).gialli_totali = None
    sessione.get(Partita, 901).stato = "PST"
    sessione.flush()
    t = ca.carica_elenco(sessione, (135,)).righe[0].totale
    assert t.partite == 7
    scheda = ca.scheda_arbitro(sessione, 1, ADESSO)
    assert scheda.senza_cartellini == 1  # 900: arbitrata ma senza cartellini; 901 non giocata


def test_scheda_totale_campionato_stagioni_ultime_e_prossima(sessione):
    _scenario(sessione)
    sc = ca.scheda_arbitro(sessione, 1, ADESSO)
    assert sc.nome == "Rossi" and sc.totale.partite == 9
    assert [(n, t.partite) for n, t in sc.per_campionato] == [("Serie A", 9)]
    assert [(c, st, t.partite) for c, st, t in sc.per_stagione] == [
        ("Serie A", "2026-27", 6), ("Serie A", "2023-24", 3),
    ]
    assert len(sc.ultime) == 9 and sc.ultime[0].stagione == "2026-27"  # dalla piu' recente
    assert [p.stagione for p in sc.ultime][-3:] == ["2023-24"] * 3
    assert sc.ultime[-1].gialli == 5 and sc.ultime[-1].rossi == 0
    # prossima: la partita futura designata, con le medie delle due squadre
    assert sc.prossima.id == PARTITA_FUTURA
    assert [c.nome for c in sc.prossima.con_squadre] == ["Casa FC", "Trasferta FC"]
    assert all(c.statistiche.partite == 9 for c in sc.prossima.con_squadre)
    assert sc.prossima.con_squadre[0].statistiche.gialli_media == 3.0


def test_scheda_ultime_al_massimo_dieci_e_arbitro_inesistente(sessione):
    _scenario(sessione)
    for i in range(5):
        _partita_2023(sessione, 800 + i, 10 + i, 4, 0, 20)
    assert len(ca.scheda_arbitro(sessione, 1, ADESSO).ultime) == ca.ULTIME_PARTITE == 10
    assert ca.scheda_arbitro(sessione, 999, ADESSO) is None


def test_prossima_partita_non_c_e_se_gia_giocata(sessione):
    _scenario(sessione)
    dopo = sessione.get(Partita, PARTITA_FUTURA).data_utc + timedelta(hours=1)
    assert ca.scheda_arbitro(sessione, 1, dopo).prossima is None


def test_etichetta_stagione_numeri_e_id():
    assert ca.etichetta_stagione(2023) == "2023-24" and ca.etichetta_stagione(2099) == "2099-00"
    assert ca.numero(None) == "–" and ca.numero(4.256) == "4,26" and ca.numero(17.5, 1) == "17,5"
    assert ca.percentuale(11.11) == "11%" and ca.percentuale(None) == "–"
    assert ca.id_arbitro("5") == 5
    assert ca.id_arbitro("x") is None and ca.id_arbitro(None) is None and ca.id_arbitro("-3") is None


def test_poche_query_qualunque_sia_il_numero_di_arbitri(sessione):
    _scenario(sessione)
    for k in range(20):
        sessione.add(Arbitro(id=100 + k, nome_normalizzato=f"a{k}", nome_visualizzato=f"Arbitro {k}"))
    sessione.flush()
    for k in range(20):
        _partita_2023(sessione, 700 + k, 30 + k, 3, 0, 20, arbitro=100 + k)
    engine = sessione.get_bind()
    conteggi = []

    def conta(*_):
        conteggi.append(1)

    event.listen(engine, "before_cursor_execute", conta)
    try:
        elenco = ca.carica_elenco(sessione, (135, 140))
        ca.scheda_arbitro(sessione, 1, ADESSO)
    finally:
        event.remove(engine, "before_cursor_execute", conta)
    assert len(elenco.righe) == 22
    assert len(conteggi) <= 12  # elenco: 2; scheda: una manciata, non una per partita


def test_aggregati_decimal_di_postgres_diventano_int():
    """Su Postgres SUM e COUNT restituiscono Decimal."""
    class Risultato:
        def all(self):
            return [(1, 135, 2023, Decimal("3"), Decimal("12"), Decimal("1"), Decimal("1"),
                     Decimal("70"), Decimal("3"))]

    class SessioneDecimal:
        def execute(self, _):
            return Risultato()

    ((chiave, t),) = ca._gruppi(SessioneDecimal()).items()
    assert chiave == (1, 135, 2023)
    for v in (t.partite, t.gialli, t.rossi, t.falli, t.partite_falli, t.con_rosso):
        assert type(v) is int
    assert t.gialli_media == 4.0 and round(t.falli_media, 2) == 23.33


# ---------------------------------------------------------------- HTML

def test_html_riga_arbitro_con_escape():
    r = ca.RigaArbitro(
        1, "<b>Rossi</b>", (135,), ca.Statistiche(10, 42, 2, 250, 10, 2)
    )
    html = stile.riga_arbitro(1, r, True)
    assert "&lt;b&gt;Rossi&lt;/b&gt;" in html and "<b>Rossi</b>" not in html
    assert "4,20" in html and "0,20" in html and "25,0" in html and "20%" in html
    assert "Serie A" in html
    assert "Serie A" not in stile.riga_arbitro(1, r, False)


def test_html_partita_arbitrata_con_escape_e_cartellini_non_noti():
    p = ca.PartitaArbitrata(
        1, "sab 08/11 20:45", "Serie A", "2023-24", "<i>Casa</i>", "Fuori", None, None, 2, 1, None, None
    )
    html = stile.partita_arbitrata(p)
    assert "&lt;i&gt;Casa&lt;/i&gt;" in html and "<i>Casa</i>" not in html
    assert "Cartellini non noti" in html
    p2 = ca.PartitaArbitrata(1, "x", "Serie A", "2023-24", "A", "B", None, None, None, None, 4, 1)
    assert "🟨 4" in stile.partita_arbitrata(p2) and "🟥 1" in stile.partita_arbitrata(p2)


def test_menu_arbitri_dopo_il_calendario():
    sorgente = (RADICE / "app" / "Partite.py").read_text(encoding="utf-8")
    assert sorgente.index("5_Calendario.py") < sorgente.index("9_Arbitri.py")
    assert 'title="Arbitri"' in sorgente


# ---------------------------------------------------------------- pagina

def test_pagina_elenco_serie_a_predefinita(sessione_db):
    with sessione_db() as s:
        _scenario(s)
    at = avvia(PAGINA_ARBITRI)
    assert not at.exception
    testo = visibile(at)
    assert ">Rossi<" in testo and "Pablo Ortega" not in testo
    assert "dal 2023-24" in testo
    link = [p for p in at.get("page_link") if p.proto.label == "Rossi"]
    assert link and link[0].proto.query_string == "arbitro=1"


def test_pagina_elenco_liga_tutti_e_ordinamento(sessione_db):
    with sessione_db() as s:
        _scenario(s)
    at = scegli_campionato(avvia(PAGINA_ARBITRI), "Liga")
    assert "Pablo Ortega" in visibile(at) and ">Rossi<" not in visibile(at)
    at = scegli_campionato(at, "Tutti")
    righe = "\n".join(m.value for m in at.markdown if "cr-ar-riga" in m.value)
    assert righe.index(">Pablo Ortega<") < righe.index(">Rossi<")
    at.selectbox(key="arbitri_criterio").select("Nome").run()
    assert not at.exception


def test_pagina_senza_arbitri(sessione_db):
    with sessione_db():
        pass
    at = avvia(PAGINA_ARBITRI)
    assert not at.exception
    assert "Nessun arbitro" in visibile(at)


def test_pagina_scheda_arbitro(sessione_db):
    with sessione_db() as s:
        _scenario(s)
    at = avvia(PAGINA_ARBITRI, arbitro=1)
    assert not at.exception
    testo = visibile(at)
    assert "Rossi" in testo and "In carriera (dal 2023-24)" in testo
    assert "Per stagione" in testo and "Ultime partite" in testo
    assert "Prossima partita designata" in testo and "Casa FC" in testo
    assert "2023-24" in testo and "2026-27" in testo
    assert any(p.proto.label == "← Tutti gli arbitri" for p in at.get("page_link"))


def test_pagina_scheda_arbitro_inesistente_o_non_valido(sessione_db):
    with sessione_db() as s:
        _scenario(s)
    assert "Arbitro non trovato" in visibile(avvia(PAGINA_ARBITRI, arbitro=999))
    at = avvia(PAGINA_ARBITRI, arbitro="abc")  # parametro non valido: torna all'elenco
    assert not at.exception and "Ordina per" in [s.label for s in at.selectbox]


def test_nome_arbitro_con_html_e_scritto_con_escape(sessione_db):
    with sessione_db() as s:
        _scenario(s)
        s.get(Arbitro, 1).nome_visualizzato = "<script>x</script>"
    for at in (avvia(PAGINA_ARBITRI), avvia(PAGINA_ARBITRI, arbitro=1)):
        assert not at.exception
        html = "\n".join(m.value for m in at.markdown)
        assert "<script>x</script>" not in html and "&lt;script&gt;" in html


def test_link_alla_scheda_dal_dettaglio_e_dalle_schede_partita(sessione_db):
    with sessione_db() as s:
        _scenario(s)
    for pagina, extra in ((PAGINA_DETTAGLIO, {"partita": PARTITA_FUTURA}), (PAGINA_PARTITE, {})):
        at = avvia(pagina, **extra)
        assert not at.exception
        link = [p for p in at.get("page_link") if "Scheda arbitro Rossi" in p.proto.label]
        assert link and link[0].proto.query_string == "arbitro=1"
        assert "Arbitri" in link[0].proto.page


def test_nessun_link_se_l_arbitro_non_e_designato(sessione_db):
    with sessione_db() as s:
        popola(s)
        s.get(Partita, PARTITA_FUTURA).arbitro_id = None
    at = avvia(PAGINA_DETTAGLIO, partita=PARTITA_FUTURA)
    assert not at.exception
    assert not [p for p in at.get("page_link") if "Scheda arbitro" in p.proto.label]


def test_cache_con_limite_di_voci():
    """Le cache delle pagine Arbitri non crescono senza limite."""
    sorgente = (Path(ayuda_app.RADICE) / "app" / "cache_dati.py").read_text(encoding="utf-8")
    for nome in ("_elenco_arbitri", "_scheda_arbitro"):
        riga = sorgente[: sorgente.index(f"def {nome}")].rsplit("@st.cache_data", 1)[1]
        assert "max_entries=" in riga.splitlines()[0]
