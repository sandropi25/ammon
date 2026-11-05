import logging
from datetime import date, datetime, timedelta, timezone

from conftest import FonteFinta, partita_dati
from sqlalchemy import select

from ammonizioni.caricamento import notturno
from ammonizioni.db import repo
from ammonizioni.db.modelli import (
    Arbitro,
    Giocata,
    Giocatore,
    Partita,
    Presenza,
    Squadra,
    UltimoAggiornamento,
)
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.giocate.registro import aggiungi_giocata


# le partite di FonteFinta sono tra il 2 e il 6 settembre 2026: tutte negli ultimi 7 giorni
ADESSO = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def esegui(s, fonte, adesso=ADESSO):
    return notturno.esegui(s, fonte, adesso=adesso)


def conta_presenze_scaricate(s) -> int:
    """Numero di partite con statistiche effettivamente salvate."""
    return len({p.partita_id for p in s.scalars(select(Presenza))})


def chieste_statistiche(fonte) -> list[int]:
    return [c[1] for c in fonte.chiamate if c[0] == "statistiche"]


def test_notte_non_scarica_lo_storico_delle_altre_competizioni(sessione):
    """Le partite giocate di coppe e stagioni passate (salvate dallo storico) restano allo
    storico: il job notturno con priorita' OGGI non spende il budget per loro."""
    vicino = ADESSO - timedelta(days=1)
    coppa = [
        partita_dati(i, vicino - timedelta(hours=i), competizione_id=137, casa=(30 + i, f"C{i}"))
        for i in (51, 52, 53)
    ]
    for dati in coppa:
        notturno.salva_partita(sessione, dati)
    notturno.salva_partita(sessione, partita_dati(60, vicino, competizione_id=2, stato="AET"))
    notturno.salva_partita(sessione, partita_dati(61, vicino, stagione=2025))  # stagione passata
    sessione.commit()
    serie_a = partita_dati(7, vicino)
    fonte = FonteFinta(calendari={(135, 2026): [serie_a], (137, 2026): coppa})
    r = esegui(sessione, fonte)
    assert r.completo is True
    assert chieste_statistiche(fonte) == [7]
    for pid in (51, 52, 53, 60, 61):
        assert sessione.get(Partita, pid).statistiche_scaricate is False


def test_notte_scarica_calendario_e_statistiche_della_liga_dopo_la_serie_a(sessione):
    vicino = ADESSO - timedelta(days=1)
    serie_a = partita_dati(7, vicino)
    liga = partita_dati(8, vicino, competizione_id=140, casa=(31, "Real"), trasferta=(32, "Barca"))
    copa = partita_dati(9, vicino, competizione_id=143, casa=(33, "A"), trasferta=(34, "B"))
    fonte = FonteFinta(calendari={(135, 2026): [serie_a], (140, 2026): [liga], (143, 2026): [copa]})
    r = esegui(sessione, fonte)
    assert r.completo is True
    # prima tutta la Serie A (calendario e statistiche), poi la Liga; la Copa del Rey allo storico
    assert fonte.chiamate == [
        ("partite", 135, 2026), ("statistiche", 7),
        ("partite", 140, 2026), ("statistiche", 8),
    ]
    assert sessione.get(Partita, 8).statistiche_scaricate is True
    assert sessione.get(Partita, 9) is None  # il calendario della coppa non e' del job notturno


def test_notte_con_il_budget_finito_ha_gia_fatto_la_serie_a(sessione):
    vicino = ADESSO - timedelta(days=1)
    serie_a = partita_dati(7, vicino)
    liga = partita_dati(8, vicino, competizione_id=140, casa=(31, "Real"), trasferta=(32, "Barca"))
    fonte = FonteFinta(calendari={(135, 2026): [serie_a], (140, 2026): [liga]}, limite_dopo=2)
    r = esegui(sessione, fonte)
    assert r.completo is False
    assert sessione.get(Partita, 7).statistiche_scaricate is True  # Serie A completa
    assert sessione.get(Partita, 8) is None  # Liga: il calendario non e' arrivato


def test_errore_sul_calendario_della_liga_non_tocca_la_serie_a(sessione, caplog):
    class FonteLigaRotta(FonteFinta):
        def partite(self, competizione_id, stagione):
            if competizione_id == 140:
                self._chiamata("partite", competizione_id, stagione)
                raise ErroreFonte("liga rotta")
            return super().partite(competizione_id, stagione)

    fonte = FonteLigaRotta(calendari={(135, 2026): [partita_dati(7, ADESSO - timedelta(days=1))]})
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.notturno"):
        r = esegui(sessione, fonte)
    assert r.completo is False
    assert sessione.get(Partita, 7).statistiche_scaricate is True
    assert any("Liga" in x.getMessage() and "liga rotta" in x.getMessage() for x in caplog.records)


def test_notte_collega_gli_arbitri_di_ogni_campionato(sessione):
    from ammonizioni.fonti.football_data import ArbitroPartita

    vicino = ADESSO - timedelta(days=1)
    liga = partita_dati(8, vicino, competizione_id=140, casa=(31, "Real Madrid CF"),
                        trasferta=(32, "FC Barcelona"), arbitro=None)
    fonte = FonteFinta(calendari={
        (135, 2026): [partita_dati(7, vicino, arbitro=None)], (140, 2026): [liga]})

    class FonteFd:
        chiave = "k"

        def __init__(self):
            self.chiamate = []

        def arbitri(self, codice, dal, al):
            self.chiamate.append(codice)
            if codice == "SA":
                return [ArbitroPartita(vicino, "Juventus FC", "FC Internazionale Milano", 1,
                                       "Daniele Doveri")]
            return [ArbitroPartita(vicino, "Real Madrid CF", "FC Barcelona", 2, "Gil Manzano")]

    fd = FonteFd()
    r = notturno.esegui(sessione, fonte, adesso=ADESSO, fonte_fd=fd)
    assert r.completo is True
    assert fd.chiamate == ["SA", "PD"]
    nome = lambda pid: sessione.get(Arbitro, sessione.get(Partita, pid).arbitro_id).nome_normalizzato  # noqa: E731
    assert (nome(7), nome(8)) == ("doveri", "140:manzano")  # gli arbitri della Liga hanno il campionato nella chiave


def test_errore_football_data_su_un_campionato_non_ferma_l_altro(sessione, caplog):
    from ammonizioni.fonti.football_data import ArbitroPartita

    vicino = ADESSO - timedelta(days=1)
    liga = partita_dati(8, vicino, competizione_id=140, casa=(31, "Real Madrid CF"),
                        trasferta=(32, "FC Barcelona"), arbitro=None)
    fonte = FonteFinta(calendari={
        (135, 2026): [partita_dati(7, vicino, arbitro=None)], (140, 2026): [liga]})

    class FonteFd:
        chiave = "k"

        def arbitri(self, codice, dal, al):
            if codice == "SA":
                raise ErroreFonte("HTTP 403")
            return [ArbitroPartita(vicino, "Real Madrid CF", "FC Barcelona", 2, "Gil Manzano")]

    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.notturno"):
        r = notturno.esegui(sessione, fonte, adesso=ADESSO, fonte_fd=FonteFd())
    assert r.completo is False
    assert sessione.get(Partita, 7).arbitro_id is None
    assert sessione.get(Partita, 8).arbitro_id is not None
    assert any("Arbitri Serie A non collegati" in x.getMessage() for x in caplog.records)


def test_statistiche_dicono_alla_fonte_la_competizione_della_partita(sessione):
    """Processo nuovo: la fonte non ha letto il calendario, la competizione arriva dal database."""
    class FonteEspnFinta(FonteFinta):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.indicate = []

        def indica_competizione(self, partita_id, competizione_id):
            self.indicate.append((partita_id, competizione_id))

    liga = partita_dati(8, ADESSO - timedelta(days=1), competizione_id=140,
                        casa=(31, "Real"), trasferta=(32, "Barca"))
    notturno.salva_partita(sessione, liga)
    sessione.commit()
    fonte = FonteEspnFinta(calendari={(140, 2026): [liga]})
    assert notturno.scarica_statistiche_partita(sessione, notturno.FonteContata(fonte), 8) is True
    assert fonte.indicate == [(8, 140)]


def test_notte_solo_partite_degli_ultimi_7_giorni(sessione):
    vecchia = partita_dati(8, ADESSO - timedelta(days=8))
    recente = partita_dati(9, ADESSO - timedelta(days=6))
    fonte = FonteFinta(calendari={(135, 2026): [vecchia, recente]})
    esegui(sessione, fonte)
    assert chieste_statistiche(fonte) == [9]
    assert sessione.get(Partita, 8).statistiche_scaricate is False


def test_notte_scarica_anche_le_partite_finite_ai_rigori(sessione):
    fonte = FonteFinta(calendari={(135, 2026): [partita_dati(9, ADESSO - timedelta(days=1), stato="PEN")]})
    esegui(sessione, fonte)
    assert chieste_statistiche(fonte) == [9]


def test_limite_a_meta_job_salva_il_parziale(sessione):
    fonte = FonteFinta(partite_ft=5, limite_dopo=3)  # la 4ª chiamata solleva LimiteSuperato
    r = esegui(sessione,fonte)
    assert r.completo is False
    assert conta_presenze_scaricate(sessione) == 2  # calendario + 2 partite
    assert repo.ultimo_aggiornamento(sessione, "notte") is not None
    assert r.richieste_usate == 3
    assert r.partite_aggiornate == 2
    # le più recenti per prime
    scaricate = {
        p.id for p in sessione.scalars(select(Partita).where(Partita.statistiche_scaricate))
    }
    assert scaricate == {5, 4}
    assert sessione.get(UltimoAggiornamento, "notte").completo is False


def test_esegui_completo(sessione):
    fonte = FonteFinta(partite_ft=3)
    r = esegui(sessione,fonte)
    assert r.completo is True
    assert r.richieste_usate == 5  # 2 calendari (Serie A, Liga) + 3 partite
    assert r.partite_aggiornate == 3
    assert conta_presenze_scaricate(sessione) == 3


def test_secondo_giro_non_riscarica(sessione):
    esegui(sessione,FonteFinta(partite_ft=3))
    fonte = FonteFinta(partite_ft=3)
    r = esegui(sessione,fonte)
    assert r.completo is True
    assert r.partite_aggiornate == 0
    assert [c[0] for c in fonte.chiamate] == ["partite", "partite"]  # Serie A e Liga


def test_partita_con_errore_saltata_le_altre_scaricate(sessione, caplog):
    fonte = FonteFinta(partite_ft=3, errori={2})
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.notturno"):
        r = esegui(sessione,fonte)
    assert r.completo is True
    assert r.partite_aggiornate == 2
    assert sessione.get(Partita, 2).statistiche_scaricate is False
    assert sessione.get(Partita, 1).statistiche_scaricate is True
    assert sessione.get(Partita, 3).statistiche_scaricate is True
    avvisi = [x for x in caplog.records if x.levelno >= logging.WARNING]
    assert len(avvisi) == 1
    assert "2" in avvisi[0].getMessage()


def test_statistiche_vuote_non_segnano_la_partita_ne_rimborsano_le_giocate(sessione, caplog):
    notturno.aggiorna_calendario(sessione, FonteFinta(partite_ft=1))
    sessione.add(Giocatore(id=101, nome="Giocatore 1"))
    giocata = aggiungi_giocata(sessione, 1, 101, "Tipster", 3.0, 10.0, date(2026, 9, 2))
    sessione.commit()
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.notturno"):
        r = esegui(sessione, FonteFinta(partite_ft=1, statistiche_vuote={1}))
    assert sessione.get(Partita, 1).statistiche_scaricate is False
    assert sessione.get(Giocata, giocata.id).esito == "in_attesa"
    assert r.partite_aggiornate == 0
    assert any("1" in x.getMessage() for x in caplog.records if x.levelno >= logging.WARNING)
    # la notte dopo la partita viene richiesta di nuovo e la giocata si chiude
    fonte = FonteFinta(partite_ft=1)
    esegui(sessione, fonte)
    assert chieste_statistiche(fonte) == [1]
    assert sessione.get(Giocata, giocata.id).esito == "vinta"


class FonteCalendarioRotto(FonteFinta):
    def partite(self, competizione_id, stagione):
        self._chiamata("partite", competizione_id, stagione)
        raise ErroreFonte("calendario rotto")


def test_errore_sul_calendario_non_ferma_statistiche_ed_esiti(sessione, caplog):
    notturno.aggiorna_calendario(sessione, FonteFinta(partite_ft=2))
    sessione.add(Giocatore(id=101, nome="Giocatore 1"))
    giocata = aggiungi_giocata(sessione, 1, 101, "Tipster", 3.0, 10.0, date(2026, 9, 2))
    sessione.commit()
    fonte = FonteCalendarioRotto(partite_ft=2)
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.notturno"):
        r = esegui(sessione, fonte)
    assert chieste_statistiche(fonte) == [2, 1]
    assert r.partite_aggiornate == 2
    assert r.completo is False
    assert sessione.get(UltimoAggiornamento, "notte").completo is False
    assert sessione.get(Giocata, giocata.id).esito == "vinta"
    assert any("calendario rotto" in x.getMessage() for x in caplog.records)


def test_scarica_statistiche_partita_vuote_restituisce_false(sessione):
    notturno.aggiorna_calendario(sessione, FonteFinta(partite_ft=1))
    fonte = FonteFinta(partite_ft=1, statistiche_vuote={1})
    assert notturno.scarica_statistiche_partita(sessione, fonte, 1) is False
    assert sessione.get(Partita, 1).statistiche_scaricate is False


def test_statistiche_vuote_dopo_3_tentativi_partita_non_serie_a_segnata_scaricata(sessione):
    """Una partita di Liga con statistiche sempre vuote dopo 3 tentativi viene segnata come
    scaricata (senza presenze) e non e' piu' richiesta; una di Serie A si richiede sempre."""
    base = datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc)
    calendari = {
        (135, 2026): [partita_dati(1, base)],
        (140, 2026): [partita_dati(2, base, competizione_id=140,
                                    casa=(31, "Real Madrid CF"), trasferta=(32, "FC Barcelona"))],
    }
    for competizione_id in (135, 140):
        notturno.aggiorna_calendario(
            sessione, FonteFinta(calendari=calendari), competizione_id=competizione_id
        )
    fonte = FonteFinta(calendari=calendari, statistiche_vuote={1, 2})
    for tentativo in (1, 2):
        assert notturno.scarica_statistiche_partita(sessione, fonte, 2) is False
        assert sessione.get(Partita, 2).statistiche_scaricate is False, tentativo
    assert notturno.scarica_statistiche_partita(sessione, fonte, 2) is False  # terzo tentativo
    assert sessione.get(Partita, 2).statistiche_scaricate is True
    assert sessione.scalars(select(Presenza).where(Presenza.partita_id == 2)).first() is None

    for _ in range(5):  # la Serie A resta da riprovare
        assert notturno.scarica_statistiche_partita(sessione, fonte, 1) is False
    assert sessione.get(Partita, 1).statistiche_scaricate is False


def test_statistiche_vuote_poi_arrivate_azzerano_i_tentativi(sessione):
    base = datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc)
    calendari = {(140, 2026): [partita_dati(2, base, competizione_id=140,
                                             casa=(31, "Real Madrid CF"),
                                             trasferta=(32, "FC Barcelona"))]}
    notturno.aggiorna_calendario(sessione, FonteFinta(calendari=calendari), competizione_id=140)
    vuota = FonteFinta(calendari=calendari, statistiche_vuote={2})
    notturno.scarica_statistiche_partita(sessione, vuota, 2)
    notturno.scarica_statistiche_partita(sessione, vuota, 2)
    assert notturno.scarica_statistiche_partita(sessione, FonteFinta(calendari=calendari), 2) is True
    assert sessione.scalars(select(Presenza).where(Presenza.partita_id == 2)).first() is not None
    assert not repo.leggi_impostazione(sessione, "statistiche_vuote_tentativi")


def test_calendario_crea_squadre_arbitro_e_non_resetta_le_statistiche(sessione):
    fonte = FonteFinta(partite_ft=1)
    notturno.aggiorna_calendario(sessione, fonte)
    assert {q.nome for q in sessione.scalars(select(Squadra))} == {"Casa 1", "Inter"}
    assert sessione.scalars(select(Arbitro)).one().nome_normalizzato == "doveri"
    assert sessione.get(Partita, 1).arbitro_id is not None
    notturno.scarica_statistiche_giocate(sessione, fonte, ADESSO)
    assert sessione.get(Partita, 1).statistiche_scaricate is True
    notturno.aggiorna_calendario(sessione, fonte)  # ripetuto: aggiorna, non duplica
    assert sessione.get(Partita, 1).statistiche_scaricate is True
    assert len(sessione.scalars(select(Partita)).all()) == 1


def test_calendario_aggiorna_risultato_e_stato(sessione):
    data = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    prima = partita_dati(7, data, stato="NS")
    dopo = partita_dati(7, data, stato="FT")
    notturno.aggiorna_calendario(sessione, FonteFinta(calendari={(135, 2026): [prima]}))
    assert sessione.get(Partita, 7).stato == "NS"
    notturno.aggiorna_calendario(sessione, FonteFinta(calendari={(135, 2026): [dopo]}))
    p = sessione.get(Partita, 7)
    assert (p.stato, p.gol_casa, p.gol_trasferta) == ("FT", 1, 0)


def test_statistiche_creano_giocatore_con_ruolo(sessione):
    esegui(sessione,FonteFinta(partite_ft=1))
    g = sessione.get(Giocatore, 101)
    assert (g.nome, g.ruolo) == ("Giocatore 1", "D")
    pr = sessione.get(Presenza, (1, 101))
    assert (pr.gialli, pr.minuti, pr.titolare) == (1, 90, True)


def test_esegui_chiude_le_giocate_delle_partite_scaricate_nel_giro(sessione):
    notturno.aggiorna_calendario(sessione, FonteFinta(partite_ft=1))
    sessione.add(Giocatore(id=101, nome="Giocatore 1"))
    giocata = aggiungi_giocata(sessione, 1, 101, "Tipster", 3.0, 10.0, date(2026, 9, 2))
    sessione.commit()
    assert giocata.esito == "in_attesa"
    esegui(sessione,FonteFinta(partite_ft=1))
    assert sessione.get(Giocata, giocata.id).esito == "vinta"