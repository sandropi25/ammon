import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from ammonizioni.fonti import espn as modulo_espn
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.espn import URL_ESPN, Espn, crea_limite_espn
from ammonizioni.fonti.limite import LimiteRichieste, LimiteSuperato, Priorita
from ammonizioni.motore.fattori.duello import avversario_diretto
from ammonizioni.motore.tipi import Titolare

DATI = Path(__file__).parent.parent / "dati_prova" / "espn"

SASSUOLO, FIORENTINA = 3997, 109
VERONA, UDINESE = 119, 118
PARTITA_SF = 401874963  # Sassuolo-Fiorentina 2 novembre 2026
PARTITA_ROSSO = 712298  # Udinese-Verona 4 gennaio 2025, rosso a Serdar al 71'
PARTITA_FUTURA = 401874815  # Venezia-Udinese 6 novembre 2026, formazioni non uscite


def carica(nome):
    return json.loads((DATI / nome).read_text(encoding="utf-8"))


@pytest.fixture
def attese():
    return []


@pytest.fixture
def espn(sessione, attese):
    limite = crea_limite_espn(sessione)
    limite.dormi = lambda s: None
    with httpx.Client() as client:
        yield Espn(limite, client=client, dormi=attese.append)


def rotta_summary(corpo, slug="ita.1", **kwargs):
    return respx.get(f"{URL_ESPN}/{slug}/summary").mock(
        return_value=httpx.Response(200, json=corpo, **kwargs)
    )


def per_id(presenze):
    return {p.giocatore_id: p for p in presenze}


def titolari_per_squadra(formazioni):
    return {f.squadra_id: f for f in formazioni}


# --- limite ----------------------------------------------------------------


def test_crea_limite_espn_valori(sessione):
    limite = crea_limite_espn(sessione)
    assert isinstance(limite, LimiteRichieste)
    assert (limite.max_minuto, limite.max_giorno, limite.riserva_oggi) == (30, 5000, 0)


@respx.mock
def test_ogni_chiamata_passa_dal_limite(sessione):
    limite = LimiteRichieste(sessione, max_giorno=1, max_minuto=30, riserva_oggi=0)
    rotta = rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    with httpx.Client() as client:
        fonte = Espn(limite, client=client, priorita=Priorita.STORICO)
        fonte.statistiche(PARTITA_SF)
        assert limite.rimanenti(Priorita.STORICO) == 0
        with pytest.raises(LimiteSuperato):
            fonte.statistiche(PARTITA_SF)
    assert rotta.call_count == 1  # la seconda non è partita


@respx.mock
def test_senza_limite_funziona_lo_stesso():
    rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    with httpx.Client() as client:
        assert Espn(client=client).statistiche(PARTITA_SF)


# --- partite ---------------------------------------------------------------


def mock_scoreboard(slug, per_data):
    for data, corpo in per_data.items():
        respx.get(f"{URL_ESPN}/{slug}/scoreboard", params={"dates": data, "limit": "1000"}).mock(
            return_value=httpx.Response(200, json=corpo)
        )


@respx.mock
def test_partite_due_chiamate_e_filtro_stagione(espn):
    mock_scoreboard("ita.1", {"2025": carica("scoreboard_2025.json"),
                              "2026": carica("scoreboard_2026.json")})
    partite = espn.partite(135, 2025)
    chiamate = respx.calls
    assert [dict(c.request.url.params)["dates"] for c in chiamate] == ["2025", "2026"]
    assert all(c.request.headers["user-agent"] == "ammonizioni/1.0" for c in chiamate)
    # 4 gennaio 2025 (stagione 2024), 1 settembre e 6 novembre 2026 (stagione 2026) esclusi
    assert [p.id for p in partite] == [736790, 736938, 737051]


@respx.mock
def test_partite_conversione(espn):
    mock_scoreboard("ita.1", {"2025": carica("scoreboard_2025.json"),
                              "2026": carica("scoreboard_2026.json")})
    p = espn.partite(135, 2025)[2]
    assert (p.id, p.competizione_id, p.stagione, p.giornata) == (737051, 135, 2025, None)
    assert (p.casa_id, p.casa_nome, p.trasferta_id, p.trasferta_nome) == (
        4050, "Cremonese", 103, "AC Milan",
    )
    assert (p.gol_casa, p.gol_trasferta, p.stato) == (0, 2, "FT")
    assert p.arbitro_nome is None
    assert p.data_utc == datetime(2026, 3, 1, 11, 30, tzinfo=timezone.utc)
    assert p.data_utc.utcoffset().total_seconds() == 0


@respx.mock
def test_partite_stagione_corrente_con_partita_da_giocare(espn):
    mock_scoreboard("ita.1", {"2026": carica("scoreboard_2026.json"), "2027": {"events": []}})
    partite = espn.partite(135, 2026)
    assert [p.id for p in partite] == [401874744, 401874815]
    futura = partite[1]
    assert (futura.stato, futura.gol_casa, futura.gol_trasferta) == ("NS", None, None)
    assert (futura.casa_nome, futura.trasferta_nome) == ("Venezia", "Udinese")


@respx.mock
def test_partite_usa_lo_slug_della_competizione(espn):
    mock_scoreboard("esp.1", {"2025": {"events": []}, "2026": {"events": []}})
    assert espn.partite(140, 2025) == []


@respx.mock
def test_partite_stati_supplementari_e_rigori(espn):
    mock_scoreboard("ita.coppa_italia", {"2024": {"events": []},
                                         "2025": carica("scoreboard_supplementari_rigori.json")})
    partite = espn.partite(137, 2024)
    assert [(p.id, p.stato, p.gol_casa, p.gol_trasferta) for p in partite] == [
        (724191, "PEN", 1, 1),
        (732195, "AET", 3, 1),
    ]


@pytest.mark.parametrize(
    "nome, atteso",
    [
        ("STATUS_FULL_TIME", "FT"),
        ("STATUS_FINAL_AET", "AET"),
        ("STATUS_FINAL_PEN", "PEN"),
        ("STATUS_SCHEDULED", "NS"),
        ("STATUS_POSTPONED", "PST"),
        ("STATUS_CANCELED", "CANC"),
        ("STATUS_ABANDONED", "STATUS_ABANDONED"),
    ],
)
@respx.mock
def test_partite_mappa_degli_stati(espn, nome, atteso):
    corpo = carica("scoreboard_2025.json")
    corpo["events"] = corpo["events"][1:2]
    corpo["events"][0]["status"]["type"]["name"] = nome
    mock_scoreboard("ita.1", {"2025": corpo, "2026": {"events": []}})
    (p,) = espn.partite(135, 2025)
    assert p.stato == atteso
    if atteso in ("NS", "PST", "CANC"):
        assert (p.gol_casa, p.gol_trasferta) == (None, None)  # ESPN dà "0" prima del via


@respx.mock
def test_partite_giornata_dalla_settimana_se_presente(espn):
    corpo = carica("scoreboard_2025.json")
    corpo["events"] = corpo["events"][1:3]
    corpo["events"][0]["week"] = {"number": 3}
    mock_scoreboard("ita.1", {"2025": corpo, "2026": {"events": []}})
    assert [p.giornata for p in espn.partite(135, 2025)] == [3, None]


@respx.mock
def test_partite_evento_malformato_saltato_con_log(espn, caplog):
    corpo = carica("scoreboard_2025.json")
    corpo["events"] = corpo["events"][1:3]
    del corpo["events"][0]["competitions"][0]["competitors"][1]
    mock_scoreboard("ita.1", {"2025": corpo, "2026": {"events": []}})
    with caplog.at_level(logging.WARNING):
        partite = espn.partite(135, 2025)
    assert [p.id for p in partite] == [736938]
    assert "736790" in caplog.text


@respx.mock
def test_partite_risposta_senza_events_errore_chiaro(espn):
    mock_scoreboard("ita.1", {"2025": {"leagues": []}, "2026": {"events": []}})
    with pytest.raises(ErroreFonte, match="events"):
        espn.partite(135, 2025)


def test_partite_competizione_sconosciuta(espn):
    with pytest.raises(ErroreFonte, match="999"):
        espn.partite(999, 2025)


@respx.mock
def test_partita_per_id_dopo_il_calendario(espn):
    mock_scoreboard("ita.1", {"2025": carica("scoreboard_2025.json"),
                              "2026": carica("scoreboard_2026.json")})
    espn.partite(135, 2025)
    assert espn.partita(736790).casa_nome == "Genoa"
    with pytest.raises(ErroreFonte, match="12345"):
        espn.partita(12345)


# --- minuti ----------------------------------------------------------------


@pytest.mark.parametrize(
    "testo, atteso",
    [("57'", 57), ("45'+2'", 45), ("45'+2", 45), ("90'+3'", 90), ("1'", 1), ("105'", 105)],
)
def test_minuto_dal_tempo_di_gioco(testo, atteso):
    assert modulo_espn._minuto({"displayValue": testo, "value": 99999.0}) == atteso


def test_minuto_dal_valore_se_manca_il_testo():
    assert modulo_espn._minuto({"value": 3481.0}) == 58
    assert modulo_espn._minuto({}) is None


# --- statistiche -----------------------------------------------------------


@respx.mock
def test_statistiche_conversione(espn):
    rotta = rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    presenze = per_id(espn.statistiche(PARTITA_SF))
    assert dict(rotta.calls.last.request.url.params) == {"event": str(PARTITA_SF)}
    assert len(presenze) == 48  # 26 + 22 convocati, panchinari inutilizzati compresi

    cande = presenze[287677]
    assert (cande.partita_id, cande.squadra_id, cande.giocatore_nome) == (
        PARTITA_SF, SASSUOLO, "Fali Candé",
    )
    assert (cande.titolare, cande.ruolo, cande.minuti) == (True, "D", 90)
    assert (cande.falli_commessi, cande.falli_subiti, cande.gialli, cande.rossi) == (4, 1, 0, 0)

    laurienté = presenze[272719]
    assert (laurienté.ruolo, laurienté.gol, laurienté.tiri, laurienté.assist) == ("F", 2, 3, 0)
    assert presenze[135743].assist == 1  # Matic
    njie = presenze[367743]
    assert (njie.squadra_id, njie.gialli, njie.ruolo) == (FIORENTINA, 1, "F")
    assert presenze[261399].ruolo == "G"
    assert presenze[272873].ruolo == "D" and presenze[135743].ruolo == "M"


@respx.mock
def test_statistiche_dati_che_espn_non_ha(espn):
    rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    for p in espn.statistiche(PARTITA_SF):
        assert (p.dribbling_tentati, p.dribbling_riusciti, p.voto) == (0, 0, None)


@respx.mock
def test_statistiche_minuti_titolare_sostituito_entrato(espn):
    rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    p = per_id(espn.statistiche(PARTITA_SF))
    assert p[261399].minuti == 90  # Turati, titolare intero
    assert p[347018].minuti == 45  # Sulemana, sostituito al 45'
    assert p[344917].minuti == 59  # Adzic, sostituito al 59'
    assert p[276254].minuti == 63  # Fagioli, sostituito al 63'
    assert p[384170].minuti == 45 and p[384170].titolare is False  # Bakola, entra al 45'
    assert p[283375].minuti == 31  # Bowie, entra al 59'
    assert p[304217].minuti == 13  # Obrador, entra al 77'
    assert p[3129533].minuti == 1  # Kulla, entra all'89'


@respx.mock
def test_statistiche_panchinaro_non_entrato_ha_zero_minuti(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    rotta_summary(corpo)
    non_entrati = [
        r for sq in corpo["rosters"] for r in sq["roster"]
        if not r["starter"] and not r["subbedIn"]
    ]
    assert len(non_entrati) == 16  # 48 convocati - 22 titolari - 10 entrati
    presenze = per_id(espn.statistiche(PARTITA_SF))
    for r in non_entrati:
        p = presenze[int(r["athlete"]["id"])]
        assert (p.titolare, p.minuti, p.ruolo, p.griglia) == (False, 0, None, None)


@respx.mock
def test_statistiche_espulso_e_sostituzioni_con_rosso(espn):
    rotta_summary(carica("summary_con_espulsione.json"))
    p = per_id(espn.statistiche(PARTITA_ROSSO))
    serdar = p[227053]
    assert (serdar.minuti, serdar.rossi, serdar.gialli, serdar.titolare) == (71, 1, 1, True)
    assert p[303752].minuti == 57  # Sarr, sostituito al 57'
    assert p[236424].minuti == 33  # Mosquera, entrato al 57'
    assert p[184737].minuti == 90  # Montipò, nessun cambio


@respx.mock
def test_statistiche_entrato_e_poi_espulso(espn):
    corpo = carica("summary_con_espulsione.json")
    corpo["keyEvents"].append({
        "type": {"id": "93", "text": "Red Card", "type": "red-card"},
        "clock": {"value": 4200.0, "displayValue": "70'"},
        "team": {"id": "119"},
        "participants": [{"athlete": {"id": "236424", "displayName": "Daniel Mosquera"}}],
    })
    rotta_summary(corpo)
    mosquera = per_id(espn.statistiche(PARTITA_ROSSO))[236424]
    assert mosquera.minuti == 13  # entrato al 57', espulso al 70'


@respx.mock
def test_statistiche_recuperi_contano_come_90(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    sostituzioni = [k for k in corpo["keyEvents"] if k["type"]["text"] == "Substitution"]
    sostituzioni[-1]["clock"]["displayValue"] = "90'+3'"  # Valdepeñas per Mastantuono
    sostituzioni[-2]["clock"]["displayValue"] = "45'+2'"  # Kulla per Esposito
    rotta_summary(corpo)
    p = per_id(espn.statistiche(PARTITA_SF))
    assert p[401558].minuti == 0  # entrato al 90'+3: nessun minuto
    assert p[376473].minuti == 90  # Mastantuono, uscito al 90'+3
    assert p[3129533].minuti == 45  # Kulla, entrato al 45'+2
    assert p[286929].minuti == 45  # Esposito, uscito al 45'+2


@respx.mock
def test_statistiche_supplementari_si_fermano_a_90(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    sostituzione = [k for k in corpo["keyEvents"] if k["type"]["text"] == "Substitution"][-1]
    sostituzione["clock"]["displayValue"] = "105'"
    rotta_summary(corpo)
    p = per_id(espn.statistiche(PARTITA_SF))
    assert p[376473].minuti == 90 and p[401558].minuti == 0


@respx.mock
def test_statistiche_sostituzione_mancante_in_key_events_usa_plays(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    corpo["keyEvents"] = [k for k in corpo["keyEvents"] if k["type"]["text"] != "Substitution"]
    for sq in corpo["rosters"]:
        for r in sq["roster"]:
            if r["athlete"]["id"] == "283375":  # Bowie
                r["plays"] = [{"clock": {"displayValue": "59'"}, "substitution": True}]
    rotta_summary(corpo)
    assert per_id(espn.statistiche(PARTITA_SF))[283375].minuti == 31


@pytest.mark.parametrize(
    "abbreviazione, ruolo",
    [
        ("G", "G"),
        ("RB", "D"), ("LB", "D"), ("CD", "D"), ("CD-R", "D"), ("CD-L", "D"),
        ("SW", "D"), ("RWB", "D"), ("LWB", "D"),
        ("CM", "M"), ("CM-R", "M"), ("CM-L", "M"), ("DM", "M"), ("DM-R", "M"),
        ("RM", "M"), ("LM", "M"), ("AM", "M"), ("AM-R", "M"), ("AM-L", "M"),
        ("F", "F"), ("CF", "F"), ("CF-R", "F"), ("CF-L", "F"), ("RF", "F"), ("LF", "F"),
        ("ST", "F"), ("RW", "F"), ("LW", "F"),
        ("XYZ", "M"),
    ],
)
@respx.mock
def test_ruolo_dalla_posizione(espn, abbreviazione, ruolo):
    corpo = carica("summary_sassuolo_fiorentina.json")
    corpo["rosters"][0]["roster"][0]["position"]["abbreviation"] = abbreviazione  # Turati
    rotta_summary(corpo)
    assert per_id(espn.statistiche(PARTITA_SF))[261399].ruolo == ruolo


@respx.mock
def test_statistiche_squadra_incompleta_senza_griglia(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    next(r for r in corpo["rosters"][1]["roster"] if r["starter"])["starter"] = False
    rotta_summary(corpo)
    presenze = espn.statistiche(PARTITA_SF)
    viola = [p for p in presenze if p.squadra_id == FIORENTINA]
    sassuolo = [p for p in presenze if p.squadra_id == SASSUOLO and p.titolare]
    assert all(p.griglia is None for p in viola)
    assert len(sassuolo) == 11 and all(p.griglia is not None for p in sassuolo)


@respx.mock
def test_statistiche_titolari_completi_hanno_griglia(espn):
    rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    titolari = [p for p in espn.statistiche(PARTITA_SF) if p.titolare]
    assert len(titolari) == 22 and all(p.griglia for p in titolari)


@respx.mock
def test_statistiche_entrato_e_poi_sostituito(espn):
    corpo = carica("summary_con_espulsione.json")
    corpo["keyEvents"].append({
        "type": {"id": "76", "text": "Substitution", "type": "substitution"},
        "clock": {"value": 4800.0, "displayValue": "80'"},
        "team": {"id": "119"},
        "participants": [
            {"athlete": {"id": "999999", "displayName": "Altro"}},
            {"athlete": {"id": "236424", "displayName": "Daniel Mosquera"}},
        ],
    })
    rotta_summary(corpo)
    assert per_id(espn.statistiche(PARTITA_ROSSO))[236424].minuti == 23  # dentro 57', fuori 80'


@respx.mock
def test_statistiche_titolare_con_posizione_sconosciuta(espn, caplog):
    corpo = carica("summary_sassuolo_fiorentina.json")
    corpo["rosters"][0]["roster"][0]["position"]["abbreviation"] = "QQ"
    rotta_summary(corpo)
    with caplog.at_level(logging.WARNING):
        turati = per_id(espn.statistiche(PARTITA_SF))[261399]
    assert turati.ruolo == "M"
    assert "QQ" in caplog.text


@respx.mock
def test_statistiche_giocatore_senza_stats_saltato(espn, caplog):
    corpo = carica("summary_sassuolo_fiorentina.json")
    del corpo["rosters"][0]["roster"][1]["stats"]  # Candé
    rotta_summary(corpo)
    with caplog.at_level(logging.WARNING):
        presenze = per_id(espn.statistiche(PARTITA_SF))
    assert len(presenze) == 47
    assert 287677 not in presenze
    assert "Candé" in caplog.text


@respx.mock
def test_statistiche_giocatore_senza_posizione_o_id_saltato(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    del corpo["rosters"][0]["roster"][0]["position"]
    del corpo["rosters"][1]["roster"][0]["athlete"]["id"]
    rotta_summary(corpo)
    assert len(espn.statistiche(PARTITA_SF)) == 46


@respx.mock
def test_statistiche_panchinaro_senza_posizione_resta(espn):
    # nelle partite più vecchie i panchinari non hanno la posizione: non vanno persi
    corpo = carica("summary_sassuolo_fiorentina.json")
    bowie = next(r for r in corpo["rosters"][0]["roster"] if r["athlete"]["id"] == "283375")
    del bowie["position"]
    rotta_summary(corpo)
    p = per_id(espn.statistiche(PARTITA_SF))[283375]
    assert (p.titolare, p.ruolo, p.minuti, p.falli_commessi) == (False, None, 31, 2)


@respx.mock
def test_statistiche_nessuno_con_stats_lista_vuota(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    for sq in corpo["rosters"]:
        for r in sq["roster"]:
            r.pop("stats", None)
    rotta_summary(corpo)
    assert espn.statistiche(PARTITA_SF) == []  # il chiamante non segna la partita come scaricata


@respx.mock
def test_statistiche_partita_non_giocata_lista_vuota(espn):
    rotta_summary(carica("summary_formazioni_non_uscite.json"))
    assert espn.statistiche(PARTITA_FUTURA) == []


@respx.mock
def test_statistiche_stats_con_valori_strani_non_rompono(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    corpo["rosters"][0]["roster"][1]["stats"] = [
        {"name": "foulsCommitted", "value": None},
        {"name": "yellowCards", "value": "x"},
        {"name": "totalShots", "value": 2.0},
    ]
    rotta_summary(corpo)
    cande = per_id(espn.statistiche(PARTITA_SF))[287677]
    assert (cande.falli_commessi, cande.gialli, cande.tiri) == (0, 0, 2)


@respx.mock
def test_statistiche_senza_rosters_errore_chiaro(espn):
    rotta_summary({"header": {}, "boxscore": {}})
    with pytest.raises(ErroreFonte, match="rosters"):
        espn.statistiche(PARTITA_SF)


@respx.mock
def test_statistiche_struttura_inattesa_errore_chiaro(espn):
    rotta_summary({"rosters": "niente"})
    with pytest.raises(ErroreFonte, match="rosters"):
        espn.statistiche(PARTITA_SF)


@respx.mock
def test_statistiche_key_events_assente_ma_titolari_ok(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    del corpo["keyEvents"]
    rotta_summary(corpo)
    p = per_id(espn.statistiche(PARTITA_SF))
    assert p[261399].minuti == 90
    assert p[347018].minuti == 90  # senza eventi non si sa dell'uscita


@respx.mock
def test_statistiche_usa_lo_slug_noto_dal_calendario(espn):
    mock_scoreboard("esp.1", {"2025": {"events": [
        carica("scoreboard_2025.json")["events"][1]]}, "2026": {"events": []}})
    espn.partite(140, 2025)
    rotta = rotta_summary(carica("summary_sassuolo_fiorentina.json"), slug="esp.1")
    espn.statistiche(736790)
    assert rotta.call_count == 1


@respx.mock
def test_competizione_indicata_dal_database_vale_per_statistiche_e_formazioni(espn):
    """Processo nuovo (nessun calendario letto): la competizione della partita, nota dal
    database, sceglie lo slug del riepilogo. Senza, una partita di Liga andrebbe a ita.1."""
    liga = rotta_summary(carica("summary_sassuolo_fiorentina.json"), slug="esp.1")
    serie_a = rotta_summary(carica("summary_sassuolo_fiorentina.json"), slug="ita.1")
    espn.indica_competizione(736790, 140)
    espn.statistiche(736790)
    espn.formazioni(736790)
    assert (liga.call_count, serie_a.call_count) == (2, 0)
    espn.indica_competizione(736790, 999)  # sconosciuta: non cambia nulla
    espn.statistiche(736790)
    assert (liga.call_count, serie_a.call_count) == (3, 0)


# --- formazioni ------------------------------------------------------------


@respx.mock
def test_formazioni_griglia_4_3_3(espn):
    rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    f = titolari_per_squadra(espn.formazioni(PARTITA_SF))
    assert set(f) == {SASSUOLO, FIORENTINA}
    assert all(x.partita_id == PARTITA_SF and len(x.titolari) == 11 for x in f.values())
    sassuolo = {gid: (ruolo, griglia) for gid, _, ruolo, griglia in f[SASSUOLO].titolari}
    # difesa da destra a sinistra (RB, CD-R, CD-L, LB), poi RM-CM-LM, poi RF-F-LF
    assert sassuolo == {
        261399: ("G", "1:1"),
        288483: ("D", "2:1"), 272873: ("D", "2:2"), 287677: ("D", "2:3"), 290418: ("D", "2:4"),
        344917: ("M", "3:1"), 135743: ("M", "3:2"), 347018: ("M", "3:3"),
        173817: ("F", "5:1"), 286929: ("F", "5:2"), 272719: ("F", "5:3"),
    }
    fiorentina = {gid: griglia for gid, _, _, griglia in f[FIORENTINA].titolari}
    assert fiorentina[367861] == "2:1"  # Jiménez RB
    assert fiorentina[139008] == "2:4"  # João Mário LB
    assert fiorentina[360061] == "3:1" and fiorentina[276237] == "3:3"  # RM e LM
    assert fiorentina[376473] == "5:1" and fiorentina[367743] == "5:3"  # RF e LF


@respx.mock
def test_formazioni_nomi_e_ruoli_come_api_football(espn):
    rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    f = titolari_per_squadra(espn.formazioni(PARTITA_SF))
    assert (261399, "Stefano Turati", "G", "1:1") in f[SASSUOLO].titolari
    assert [t[0] for t in f[SASSUOLO].titolari][0] == 261399  # prima il portiere


@respx.mock
def test_formazioni_griglia_3_4_1_2(espn):
    rotta_summary(carica("summary_con_espulsione.json"))
    f = titolari_per_squadra(espn.formazioni(PARTITA_ROSSO))
    verona = {gid: griglia for gid, _, _, griglia in f[VERONA].titolari}
    assert (verona[190805], verona[332549], verona[340705]) == ("2:1", "2:2", "2:3")  # CD-R, CD, CD-L
    # RM, CM-R, CM-L, LM
    assert (verona[312186], verona[227053], verona[206072], verona[276582]) == (
        "3:1", "3:2", "3:3", "3:4",
    )
    assert verona[301665] == "4:1"  # AM
    assert (verona[303752], verona[306664]) == ("5:1", "5:2")  # CF-R, CF-L
    udinese = {gid: griglia for gid, _, _, griglia in f[UDINESE].titolari}
    # 3-5-2: RM, CM-R, CM-L, LM in riga 3, AM in riga 4
    assert (udinese[212476], udinese[219725], udinese[262565], udinese[193919]) == (
        "3:1", "3:2", "3:3", "3:4",
    )
    assert udinese[237055] == "4:1"


def squadra_sintetica(team_id, posizioni):
    roster = []
    for i, abbreviazione in enumerate(posizioni, start=1):
        roster.append({
            "starter": True, "subbedIn": False, "subbedOut": False,
            "position": {"abbreviation": abbreviazione}, "formationPlace": str(i),
            "athlete": {"id": str(team_id * 100 + i), "displayName": f"Giocatore {abbreviazione}"},
            "stats": [{"name": "appearances", "value": 1.0}],
        })
    return {"homeAway": "home", "team": {"id": str(team_id), "displayName": "Prova"},
            "roster": roster}


@respx.mock
def test_formazioni_griglia_4_2_3_1(espn):
    # ordine volutamente mescolato: conta la posizione, non l'ordine dei dati
    posizioni = ["F", "AM-L", "CM-L", "LB", "G", "AM", "CD-R", "RB", "CM-R", "AM-R", "CD-L"]
    rotta_summary({"rosters": [squadra_sintetica(1, posizioni)], "keyEvents": []})
    (f,) = espn.formazioni(1)
    griglia = {nome: g for _, nome, _, g in f.titolari}
    assert griglia["Giocatore G"] == "1:1"
    assert [griglia[f"Giocatore {x}"] for x in ("RB", "CD-R", "CD-L", "LB")] == [
        "2:1", "2:2", "2:3", "2:4",
    ]
    assert [griglia[f"Giocatore {x}"] for x in ("CM-R", "CM-L")] == ["3:1", "3:2"]
    assert [griglia[f"Giocatore {x}"] for x in ("AM-R", "AM", "AM-L")] == ["4:1", "4:2", "4:3"]
    assert griglia["Giocatore F"] == "5:1"


@respx.mock
def test_formazioni_posizione_sconosciuta_riga_3_centro_con_log(espn, caplog):
    posizioni = ["G", "RB", "CD-R", "CD-L", "LB", "RM", "CM", "LM", "XX", "RF", "LF"]
    rotta_summary({"rosters": [squadra_sintetica(1, posizioni)]})
    with caplog.at_level(logging.WARNING):
        (f,) = espn.formazioni(1)
    d = {nome: (ruolo, g) for _, nome, ruolo, g in f.titolari}
    # riga 3: RM, poi i due centrali (CM e lo sconosciuto, in ordine di formationPlace), LM
    assert d["Giocatore RM"] == ("M", "3:1")
    assert d["Giocatore CM"] == ("M", "3:2")
    assert d["Giocatore XX"] == ("M", "3:3")
    assert d["Giocatore LM"] == ("M", "3:4")
    assert "XX" in caplog.text


@respx.mock
def test_avversario_diretto_terzino_destro_contro_esterno_sinistro(espn):
    rotta_summary(carica("summary_sassuolo_fiorentina.json"))
    f = titolari_per_squadra(espn.formazioni(PARTITA_SF))

    def titolari(squadra_id):
        return [
            Titolare(gid, nome, squadra_id, ruolo, griglia, None)
            for gid, nome, ruolo, griglia in f[squadra_id].titolari
        ]

    sassuolo, fiorentina = titolari(SASSUOLO), titolari(FIORENTINA)
    terzino_destro = next(t for t in sassuolo if t.giocatore_id == 288483)  # Walukiewicz
    assert avversario_diretto(terzino_destro, fiorentina, None, sassuolo) == 367743  # Njie, LF
    terzino_sinistro = next(t for t in sassuolo if t.giocatore_id == 290418)  # Doig
    assert avversario_diretto(terzino_sinistro, fiorentina, None, sassuolo) == 376473  # Mastantuono, RF
    # e al contrario: l'esterno sinistro viola contro il terzino destro del Sassuolo
    njie = next(t for t in fiorentina if t.giocatore_id == 367743)
    assert avversario_diretto(njie, sassuolo, None, fiorentina) == 288483


@respx.mock
def test_formazioni_non_uscite_lista_vuota(espn):
    rotta_summary(carica("summary_formazioni_non_uscite.json"))
    assert espn.formazioni(PARTITA_FUTURA) == []


@respx.mock
def test_formazioni_senza_undici_titolari_lista_vuota(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    for sq in corpo["rosters"]:
        primo = next(r for r in sq["roster"] if r["starter"])
        primo["starter"] = False
    rotta_summary(corpo)
    assert espn.formazioni(PARTITA_SF) == []


@respx.mock
def test_formazioni_una_sola_squadra_completa(espn):
    corpo = carica("summary_sassuolo_fiorentina.json")
    primo = next(r for r in corpo["rosters"][1]["roster"] if r["starter"])
    primo["starter"] = False
    rotta_summary(corpo)
    f = espn.formazioni(PARTITA_SF)
    assert [x.squadra_id for x in f] == [SASSUOLO]


@respx.mock
def test_formazioni_senza_rosters_errore_chiaro(espn):
    rotta_summary({"header": {}})
    with pytest.raises(ErroreFonte, match="rosters"):
        espn.formazioni(PARTITA_SF)


# --- HTTP, retry -----------------------------------------------------------


@respx.mock
def test_retry_su_500_e_429_poi_ok(espn, attese):
    rotta = respx.get(f"{URL_ESPN}/ita.1/summary").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(429),
            httpx.Response(200, json=carica("summary_sassuolo_fiorentina.json")),
        ]
    )
    assert espn.statistiche(PARTITA_SF)
    assert rotta.call_count == 3
    assert attese == [1, 2]


@respx.mock
def test_retry_su_errore_di_rete(espn, attese):
    rotta = respx.get(f"{URL_ESPN}/ita.1/summary").mock(
        side_effect=[
            httpx.ConnectError("giù"),
            httpx.Response(200, json=carica("summary_sassuolo_fiorentina.json")),
        ]
    )
    assert espn.statistiche(PARTITA_SF)
    assert rotta.call_count == 2 and attese == [1]


@respx.mock
def test_tentativi_esauriti_errore_fonte(espn, attese):
    rotta = respx.get(f"{URL_ESPN}/ita.1/summary").mock(return_value=httpx.Response(503))
    with pytest.raises(ErroreFonte, match="5 tentativi"):
        espn.statistiche(PARTITA_SF)
    assert rotta.call_count == 5
    assert attese == [1, 2, 4, 8]


@respx.mock
def test_ogni_tentativo_consuma_una_richiesta_del_limite(sessione, attese):
    limite = crea_limite_espn(sessione)
    limite.dormi = lambda s: None
    respx.get(f"{URL_ESPN}/ita.1/summary").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=carica("summary_sassuolo_fiorentina.json"))]
    )
    with httpx.Client() as client:
        Espn(limite, client=client, dormi=attese.append).statistiche(PARTITA_SF)
    assert limite.rimanenti(Priorita.OGGI) == 5000 - 2


@respx.mock
def test_404_errore_subito_senza_retry(espn, attese):
    rotta = respx.get(f"{URL_ESPN}/ita.1/summary").mock(return_value=httpx.Response(404))
    with pytest.raises(ErroreFonte, match="404"):
        espn.statistiche(PARTITA_SF)
    assert rotta.call_count == 1 and attese == []


@respx.mock
def test_risposta_non_json_errore_fonte(espn):
    respx.get(f"{URL_ESPN}/ita.1/summary").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(ErroreFonte, match="non valida"):
        espn.statistiche(PARTITA_SF)


@respx.mock
def test_risposta_json_non_oggetto_errore_fonte(espn):
    respx.get(f"{URL_ESPN}/ita.1/summary").mock(return_value=httpx.Response(200, json=[1, 2]))
    with pytest.raises(ErroreFonte, match="non valida"):
        espn.statistiche(PARTITA_SF)
