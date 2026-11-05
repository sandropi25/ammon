import logging
from datetime import date, datetime, timedelta, timezone

from conftest import FonteFinta, partita_dati
from sqlalchemy import select

from ammonizioni.caricamento import storico
from ammonizioni.config import COMPETIZIONI, STAGIONE_CORRENTE, STAGIONI
from ammonizioni.db import repo
from ammonizioni.db.modelli import Partita, Presenza, UltimoAggiornamento
from ammonizioni.caricamento.notturno import salva_partita

OGGI = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
CARICATE = tuple(COMPETIZIONI.values())  # tutte e 7: due campionati, due coppe, tre europee
CALENDARI = len(CARICATE) * len(STAGIONI) - 2  # tutti tranne i campionati della stagione corrente


def _salva(s, *partite):
    for p in partite:
        salva_partita(s, p)
    s.commit()


def test_storico_prima_le_squadre_della_prossima_giornata(sessione):
    giorno = lambda n: OGGI - timedelta(days=n)
    _salva(
        sessione,
        # prossima giornata di Serie A: giocano le squadre 3 e 4
        partita_dati(100, OGGI + timedelta(days=2), casa=(3, "C"), trasferta=(4, "D"), stato="NS"),
        # troppo in là: le squadre 11 e 12 non contano
        partita_dati(101, OGGI + timedelta(days=9), casa=(11, "K"), trasferta=(12, "L"), stato="NS"),
        # giocate, da scaricare
        partita_dati(10, giorno(1), casa=(5, "E"), trasferta=(6, "F")),
        partita_dati(11, giorno(5), casa=(3, "C"), trasferta=(7, "G")),
        partita_dati(12, giorno(9), casa=(8, "H"), trasferta=(9, "I")),
        partita_dati(13, giorno(30), casa=(4, "D"), trasferta=(13, "M"), competizione_id=137),
        partita_dati(14, giorno(2), casa=(11, "K"), trasferta=(14, "N")),
        # da escludere: già scaricata, stagione fuori storico, competizione non coperta
        partita_dati(20, giorno(3), casa=(3, "C"), trasferta=(7, "G")),
        partita_dati(21, giorno(4), casa=(3, "C"), trasferta=(7, "G"), stagione=2023),
        partita_dati(22, giorno(6), casa=(3, "C"), trasferta=(7, "G"), competizione_id=999),
    )
    sessione.get(Partita, 20).statistiche_scaricate = True
    sessione.commit()

    # prima 11 e 13 (squadre 3 e 4, dalla più recente), poi 10, 14, 12 (dalla più recente)
    assert storico.prossime_da_scaricare(sessione, OGGI) == [11, 13, 10, 14, 12]


def test_storico_prende_anche_le_partite_finite_ai_supplementari_o_ai_rigori(sessione):
    _salva(
        sessione,
        partita_dati(30, OGGI - timedelta(days=1), competizione_id=137, stato="AET"),
        partita_dati(31, OGGI - timedelta(days=2), competizione_id=2, stato="PEN"),
        partita_dati(32, OGGI - timedelta(days=3), stato="FT"),
        partita_dati(33, OGGI - timedelta(days=4), stato="PST"),  # non giocata: esclusa
    )
    assert storico.prossime_da_scaricare(sessione, OGGI) == [30, 31, 32]


def test_coda_storico_tutte_le_coppie_tranne_il_calendario_notturno(sessione):
    coda = storico.coda_storico(sessione, OGGI)
    assert len(coda) == CALENDARI
    assert (COMPETIZIONI["serie_a"], STAGIONE_CORRENTE) not in coda
    assert {c for c, _ in coda} == set(CARICATE)
    # dentro ogni gruppo (Serie A e coppe, poi Liga e Copa del Rey) le stagioni recenti per prime
    for gruppo in (coda[:CALENDARI - 5], coda[CALENDARI - 5:]):
        assert [st for _, st in gruppo] == sorted((st for _, st in gruppo), reverse=True)


def test_coda_storico_i_calendari_della_liga_dopo_quelli_della_serie_a(sessione):
    coda = storico.coda_storico(sessione, OGGI)
    liga = {COMPETIZIONI["liga"], COMPETIZIONI["copa_del_rey"]}
    posizioni = [i for i, (c, _) in enumerate(coda) if c in liga]
    altre = [i for i, (c, _) in enumerate(coda) if c not in liga]
    assert len(posizioni) == 5 and max(altre) < min(posizioni)
    # la Serie A del 2025 e del 2024 prima di qualsiasi Liga; i campionati della stagione
    # corrente non sono in coda (li scarica il job notturno), la Copa del Rey si'
    assert (COMPETIZIONI["serie_a"], 2025) in [coda[i] for i in altre]
    assert (COMPETIZIONI["liga"], STAGIONE_CORRENTE) not in coda
    assert (COMPETIZIONI["serie_a"], STAGIONE_CORRENTE) not in coda
    assert coda[min(posizioni)] == (COMPETIZIONI["copa_del_rey"], STAGIONE_CORRENTE)


def test_prossime_da_scaricare_serie_a_prima_della_liga(sessione):
    """Anche se le partite di Liga sono piu' recenti o di squadre che giocano a breve: prima
    la Serie A, poi le coppe di squadre di Serie A, poi la Liga; coppe europee tra squadre
    senza campionato in fondo."""
    giorno = lambda n: OGGI - timedelta(days=n)  # noqa: E731
    _salva(
        sessione,
        # Serie A: giocano le squadre 3 e 4 tra 2 giorni; Liga: le squadre 53 e 54
        partita_dati(100, OGGI + timedelta(days=2), casa=(3, "C"), trasferta=(4, "D"), stato="NS"),
        partita_dati(101, OGGI + timedelta(days=2), competizione_id=140, casa=(53, "R"),
                     trasferta=(54, "B"), stato="NS"),
        # da scaricare
        partita_dati(10, giorno(40), casa=(5, "E"), trasferta=(6, "F")),                  # Serie A
        partita_dati(11, giorno(1), competizione_id=140, casa=(53, "R"), trasferta=(55, "S")),  # Liga
        partita_dati(12, giorno(2), competizione_id=140, casa=(56, "T"), trasferta=(57, "U")),  # Liga
        partita_dati(13, giorno(3), competizione_id=143, casa=(56, "T"), trasferta=(58, "V")),  # Copa
        partita_dati(14, giorno(30), competizione_id=137, casa=(5, "E"), trasferta=(59, "W")),  # Coppa Italia
        # europea con una squadra di Serie A (la 7) e una di Liga: vale la Serie A
        partita_dati(15, giorno(1), competizione_id=2, casa=(7, "G"), trasferta=(55, "S")),
        # europea tra due squadre di Liga
        partita_dati(16, OGGI - timedelta(hours=60), competizione_id=2, casa=(56, "T"),
                     trasferta=(60, "X")),
        # europea tra squadre di nessun campionato
        partita_dati(17, giorno(2), competizione_id=3, casa=(70, "P"), trasferta=(71, "Q")),
    )
    # la squadra 7 e' di Serie A (ha una partita di campionato), le 55-58 di Liga
    _salva(
        sessione,
        partita_dati(110, giorno(100), casa=(7, "G"), trasferta=(5, "E")),
        partita_dati(111, giorno(100), competizione_id=140, casa=(55, "S"), trasferta=(56, "T")),
        partita_dati(112, giorno(100), competizione_id=140, casa=(58, "V"), trasferta=(60, "X")),
    )
    for pid in (110, 111, 112):
        sessione.get(Partita, pid).statistiche_scaricate = True
    sessione.commit()

    ordine = storico.prossime_da_scaricare(sessione, OGGI)
    # Serie A: 10, 14 (Coppa Italia), 15 (europea con la 7), nessuna gioca a breve: dalla piu'
    # recente. Liga: prima chi gioca a breve (11, con la 53), poi 12, 16, 13 per data.
    # In fondo la 17.
    assert ordine == [15, 14, 10, 11, 12, 16, 13, 17]


def test_prossime_da_scaricare_serie_a_prima_anche_se_la_liga_gioca_a_breve(sessione):
    giorno = lambda n: OGGI - timedelta(days=n)  # noqa: E731
    _salva(
        sessione,
        partita_dati(101, OGGI + timedelta(days=2), competizione_id=140, casa=(53, "R"),
                     trasferta=(54, "B"), stato="NS"),
        partita_dati(10, giorno(60), casa=(5, "E"), trasferta=(6, "F")),
        partita_dati(11, giorno(1), competizione_id=140, casa=(53, "R"), trasferta=(55, "S")),
    )
    assert storico.prossime_da_scaricare(sessione, OGGI) == [10, 11]


def test_coda_storico_salta_i_calendari_gia_scaricati(sessione):
    repo.scrivi_impostazione(sessione, "calendari_scaricati", [[137, 2025], [2, 2024]])
    coda = storico.coda_storico(sessione, OGGI)
    assert (137, 2025) not in coda and (2, 2024) not in coda
    assert len(coda) == CALENDARI - 2


def test_calendari_stagione_corrente_non_serie_a_riscaricati_dopo_7_giorni(sessione):
    tutti = [
        [c, st] for st in STAGIONI for c in CARICATE
        if (c, st) != (135, STAGIONE_CORRENTE)
    ]
    repo.scrivi_impostazione(sessione, "calendari_scaricati", tutti)
    repo.scrivi_impostazione(
        sessione,
        "calendari_scaricati_il",
        {
            "137-2026": (OGGI - timedelta(days=8)).isoformat(),   # scaduto
            "2-2026": (OGGI - timedelta(days=2)).isoformat(),     # recente
            "137-2025": (OGGI - timedelta(days=300)).isoformat(),  # passata: mai
        },
    )
    coda = storico.coda_storico(sessione, OGGI)
    assert (137, 2026) in coda
    assert (2, 2026) not in coda
    assert (137, 2025) not in coda
    # data ignota per la stagione corrente: da riscaricare; stagioni passate mai
    assert (3, 2026) in coda and (3, 2025) not in coda
    assert (135, 2026) not in coda


def test_avanza_scarica_calendari_poi_statistiche(sessione):
    base = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    calendari = {
        (137, 2025): [partita_dati(1, base, competizione_id=137, stagione=2025)],
        (135, 2025): [partita_dati(2, base + timedelta(days=1), stagione=2025)],
    }
    fonte = FonteFinta(calendari=calendari)
    r = storico.avanza(sessione, fonte)
    assert r.completo is True
    assert r.partite_aggiornate == 2
    assert r.richieste_usate == CALENDARI + 2
    nomi = [c[0] for c in fonte.chiamate]
    assert nomi == ["partite"] * CALENDARI + ["statistiche"] * 2
    assert [c[1] for c in fonte.chiamate if c[0] == "statistiche"] == [2, 1]  # più recente prima
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == CALENDARI
    assert repo.ultimo_aggiornamento(sessione, "storico") is not None

    # secondo giro: niente da fare
    fonte2 = FonteFinta(calendari=calendari)
    r2 = storico.avanza(sessione, fonte2)
    assert (r2.completo, r2.richieste_usate, fonte2.chiamate) == (True, 0, [])


def test_avanza_limite_a_meta_salva_il_parziale(sessione):
    base = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    calendari = {(135, 2025): [partita_dati(i, base + timedelta(days=i), stagione=2025) for i in (1, 2, 3)]}
    fonte = FonteFinta(calendari=calendari, limite_dopo=CALENDARI + 1)  # tutti i calendari + 1 partita
    r = storico.avanza(sessione, fonte)
    assert r.completo is False
    assert r.partite_aggiornate == 1
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == CALENDARI
    assert len({p.partita_id for p in sessione.scalars(select(Presenza))}) == 1
    assert sessione.get(UltimoAggiornamento, "storico").completo is False


def test_avanza_limite_durante_i_calendari(sessione):
    fonte = FonteFinta(calendari={}, limite_dopo=3)
    r = storico.avanza(sessione, fonte)
    assert r.completo is False
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == 3


def test_avanza_calendario_con_errore_saltato(sessione, caplog):
    class FonteCalendarioRotto(FonteFinta):
        def partite(self, competizione_id, stagione):
            if (competizione_id, stagione) == (137, 2025):
                self._chiamata("partite", competizione_id, stagione)
                from ammonizioni.fonti.base import ErroreFonte

                raise ErroreFonte("calendario rotto")
            return super().partite(competizione_id, stagione)

    fonte = FonteCalendarioRotto(calendari={})
    r = storico.avanza(sessione, fonte)
    assert r.completo is True
    assert [137, 2025] not in repo.leggi_impostazione(sessione, "calendari_scaricati")
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == CALENDARI - 1
    assert any("137" in x.getMessage() for x in caplog.records)


# --- tempo massimo e arbitri -----------------------------------------------------


class Orologio:
    """Orologio finto: il tempo avanza solo quando la fonte scarica statistiche."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FonteLenta(FonteFinta):
    def __init__(self, orologio, minuti_a_statistica=1, **kwargs):
        super().__init__(**kwargs)
        self.orologio = orologio
        self.minuti = minuti_a_statistica

    def statistiche(self, partita_id):
        self.orologio.t += self.minuti * 60
        return super().statistiche(partita_id)


def _calendario_2025(n=5):
    base = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    return {
        (135, 2025): [
            partita_dati(i, base + timedelta(days=i), stagione=2025, arbitro=None)  # come ESPN
            for i in range(1, n + 1)
        ]
    }


def test_avanza_si_ferma_al_tempo_massimo_e_riprende(sessione):
    orologio = Orologio()
    fonte = FonteLenta(orologio, calendari=_calendario_2025())
    r = storico.avanza(sessione, fonte, orologio=orologio, max_minuti=2)
    assert r.completo is False
    assert r.partite_aggiornate == 2  # una al minuto, poi basta
    assert [c[1] for c in fonte.chiamate if c[0] == "statistiche"] == [5, 4]
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == CALENDARI  # calendari fatti
    assert sessione.get(UltimoAggiornamento, "storico").completo is False
    assert {p.partita_id for p in sessione.scalars(select(Presenza))} == {5, 4}

    # la notte dopo continua dalle rimanenti, senza rifare nulla
    orologio2 = Orologio()
    fonte2 = FonteLenta(orologio2, calendari=_calendario_2025())
    r2 = storico.avanza(sessione, fonte2, orologio=orologio2, max_minuti=40)
    assert r2.completo is True
    assert [c[1] for c in fonte2.chiamate if c[0] == "statistiche"] == [3, 2, 1]
    assert [c for c in fonte2.chiamate if c[0] == "partite"] == []


def test_avanza_tempo_esaurito_durante_i_calendari(sessione):
    class Fonte(FonteFinta):
        def __init__(self, orologio, **kwargs):
            super().__init__(**kwargs)
            self.orologio = orologio

        def partite(self, competizione_id, stagione):
            self.orologio.t += 60
            return super().partite(competizione_id, stagione)

    orologio = Orologio()
    r = storico.avanza(sessione, Fonte(orologio, calendari={}), orologio=orologio, max_minuti=3)
    assert r.completo is False
    assert len(repo.leggi_impostazione(sessione, "calendari_scaricati")) == 3


def test_avanza_tempo_massimo_da_env(sessione, monkeypatch):
    monkeypatch.delenv("STORICO_MAX_MINUTI", raising=False)
    assert storico.max_minuti_da_env() == 40
    monkeypatch.setenv("STORICO_MAX_MINUTI", "")
    assert storico.max_minuti_da_env() == 40
    monkeypatch.setenv("STORICO_MAX_MINUTI", "2")
    orologio = Orologio()
    fonte = FonteLenta(orologio, calendari=_calendario_2025())
    r = storico.avanza(sessione, fonte, orologio=orologio)  # il tetto viene dall'ambiente
    assert (r.completo, r.partite_aggiornate) == (False, 2)


class FonteFdStagioni:
    def __init__(self, voci, chiave="k"):
        self.voci, self.chiave, self.chiamate = voci, chiave, []

    def arbitri(self, codice, dal, al):
        self.chiamate.append((codice, dal, al))
        return list(self.voci)


def test_avanza_collega_gli_arbitri_una_volta_per_stagione_intera(sessione):
    from ammonizioni.db.modelli import Arbitro
    from ammonizioni.fonti.football_data import ArbitroPartita

    cal = _calendario_2025(2)
    voci = [
        ArbitroPartita(p.data_utc, "Juventus FC", "FC Internazionale Milano", 1, "Davide Massa")
        for p in cal[(135, 2025)]
    ]
    fd = FonteFdStagioni(voci)
    storico.avanza(sessione, FonteFinta(calendari=cal), fd)
    assert fd.chiamate == [("SA", date(2025, 7, 1), date(2026, 6, 30))]  # una richiesta, 2025
    for partita_id in (1, 2):
        arbitro_id = sessione.get(Partita, partita_id).arbitro_id
        assert sessione.get(Arbitro, arbitro_id).nome_normalizzato == "massa"
    assert repo.leggi_impostazione(sessione, "arbitri_collegati") == [2025]

    storico.avanza(sessione, FonteFinta(calendari=cal), fd)  # notte dopo: niente di nuovo
    assert len(fd.chiamate) == 1


def test_avanza_collega_gli_arbitri_anche_della_liga_dopo_la_serie_a(sessione):
    from ammonizioni.db.modelli import Arbitro
    from ammonizioni.fonti.football_data import ArbitroPartita

    base = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    cal = {
        (135, 2025): [partita_dati(1, base, stagione=2025, arbitro=None)],
        (140, 2025): [partita_dati(2, base, competizione_id=140, stagione=2025, arbitro=None,
                                   casa=(31, "Real Madrid CF"), trasferta=(32, "FC Barcelona"))],
    }

    class Fd(FonteFdStagioni):
        def arbitri(self, codice, dal, al):
            self.chiamate.append((codice, dal, al))
            if codice == "SA":
                return [ArbitroPartita(base, "Juventus FC", "FC Internazionale Milano", 1,
                                       "Davide Massa")]
            return [ArbitroPartita(base, "Real Madrid CF", "FC Barcelona", 2, "Gil Manzano")]

    fd = Fd([])
    storico.avanza(sessione, FonteFinta(calendari=cal), fd)
    stagione = (date(2025, 7, 1), date(2026, 6, 30))
    assert fd.chiamate == [("SA", *stagione), ("PD", *stagione)]  # Serie A per prima
    nome = lambda pid: sessione.get(Arbitro, sessione.get(Partita, pid).arbitro_id).nome_normalizzato  # noqa: E731
    assert (nome(1), nome(2)) == ("massa", "140:manzano")
    assert repo.leggi_impostazione(sessione, "arbitri_collegati") == [2025]  # chiave invariata
    assert repo.leggi_impostazione(sessione, "arbitri_collegati_140") == [2025]

    storico.avanza(sessione, FonteFinta(calendari=cal), fd)  # notte dopo: niente di nuovo
    assert len(fd.chiamate) == 2


def test_avanza_ricollega_ogni_settimana_gli_arbitri_della_stagione_corrente(sessione):
    """Una partita della stagione corrente senza arbitro (designato dopo il primo collegamento)
    viene ricollegata dopo 7 giorni, con una richiesta per campionato; non prima."""
    from ammonizioni.db.modelli import Arbitro
    from ammonizioni.fonti.football_data import ArbitroPartita

    data = datetime.now(timezone.utc) - timedelta(days=10)
    _salva(sessione, partita_dati(1, data, stagione=STAGIONE_CORRENTE, arbitro=None,
                                  stato="NS"))
    voce = ArbitroPartita(data, "Juventus FC", "FC Internazionale Milano", 1, "Davide Massa")
    fd = FonteFdStagioni([])  # al primo passaggio football-data non ha ancora l'arbitro
    storico.avanza(sessione, FonteFinta(), fd)
    intera = (date(STAGIONE_CORRENTE, 7, 1), date(STAGIONE_CORRENTE + 1, 6, 30))
    assert fd.chiamate == [("SA", *intera)]  # niente richieste per la Liga: nessuna partita
    assert sessione.get(Partita, 1).arbitro_id is None

    fd.voci = [voce]
    storico.avanza(sessione, FonteFinta(), fd)  # meno di 7 giorni dopo: non riprova
    assert len(fd.chiamate) == 1 and sessione.get(Partita, 1).arbitro_id is None

    quando = repo.leggi_impostazione(sessione, "arbitri_ricollegati_il")
    quando["135"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    repo.scrivi_impostazione(sessione, "arbitri_ricollegati_il", quando)
    sessione.commit()
    storico.avanza(sessione, FonteFinta(), fd)
    assert fd.chiamate[1:] == [("SA", *intera)]
    arbitro_id = sessione.get(Partita, 1).arbitro_id
    assert sessione.get(Arbitro, arbitro_id).nome_normalizzato == "massa"

    storico.avanza(sessione, FonteFinta(), fd)  # fatto: la settimana riparte
    assert len(fd.chiamate) == 2


def test_avanza_senza_chiave_football_data_non_segna_le_stagioni(sessione, caplog):
    cal = _calendario_2025(1)
    fd = FonteFdStagioni([], chiave=None)
    with caplog.at_level("WARNING"):
        storico.avanza(sessione, FonteFinta(calendari=cal), fd)
    assert fd.chiamate == []
    assert not repo.leggi_impostazione(sessione, "arbitri_collegati")
    assert "FOOTBALL_DATA_KEY" in caplog.text


def test_avanza_errore_football_data_stagione_da_riprovare(sessione, caplog):
    from ammonizioni.fonti.base import ErroreFonte

    class Rotta(FonteFdStagioni):
        def arbitri(self, codice, dal, al):
            super().arbitri(codice, dal, al)
            raise ErroreFonte("HTTP 403")

    fd = Rotta([])
    r = storico.avanza(sessione, FonteFinta(calendari=_calendario_2025(1)), fd)
    assert r.completo is False  # statistiche scaricate comunque
    assert r.partite_aggiornate == 1
    assert not repo.leggi_impostazione(sessione, "arbitri_collegati")
    assert any("2025" in x.getMessage() and "HTTP 403" in x.getMessage() for x in caplog.records)


def test_avanza_non_collega_stagioni_senza_calendario(sessione):
    fd = FonteFdStagioni([])
    storico.avanza(sessione, FonteFinta(calendari={}), fd)
    assert fd.chiamate == []  # nessuna partita nel database: niente da collegare
    assert not repo.leggi_impostazione(sessione, "arbitri_collegati")


def test_max_minuti_non_numerico_usa_il_default_con_avviso(monkeypatch, caplog):
    monkeypatch.setenv("STORICO_MAX_MINUTI", "quaranta")
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.storico"):
        assert storico.max_minuti_da_env() == 40
    assert any("STORICO_MAX_MINUTI" in x.getMessage() for x in caplog.records)


def test_stagioni_gia_collegate_ricevono_la_giornata_una_volta_sola(sessione):
    """Stagione con gli arbitri gia' collegati prima delle giornate: una richiesta per campionato
    e stagione, poi il flag `giornate_collegate` evita di ripeterla ogni notte."""
    from ammonizioni.fonti.football_data import ArbitroPartita

    data = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    _salva(sessione, partita_dati(1, data, stagione=2025, giornata=None))
    sessione.get(Partita, 1).statistiche_scaricate = True
    repo.scrivi_impostazione(sessione, "arbitri_collegati", [2025])  # gia' collegata in passato
    sessione.commit()
    fd = FonteFdStagioni([
        ArbitroPartita(data, "Juventus FC", "FC Internazionale Milano", 1, "Davide Massa", 22)
    ])
    storico.avanza(sessione, FonteFinta(), fd)
    assert fd.chiamate == [("SA", date(2025, 7, 1), date(2026, 6, 30))]  # una sola richiesta
    assert sessione.get(Partita, 1).giornata == 22
    assert repo.leggi_impostazione(sessione, "giornate_collegate") == [2025]

    storico.avanza(sessione, FonteFinta(), fd)
    storico.avanza(sessione, FonteFinta(), fd)  # notti dopo: niente di nuovo
    assert len(fd.chiamate) == 1


def test_giornata_non_trovata_non_si_richiede_ogni_notte(sessione):
    from ammonizioni.fonti.football_data import ArbitroPartita

    data = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    _salva(sessione, partita_dati(1, data, stagione=2025, giornata=None))
    sessione.get(Partita, 1).statistiche_scaricate = True
    repo.scrivi_impostazione(sessione, "arbitri_collegati", [2025])
    sessione.commit()
    fd = FonteFdStagioni([ArbitroPartita(data, "Torino FC", "Udinese Calcio", 1, "X Y", 3)])
    storico.avanza(sessione, FonteFinta(), fd)
    storico.avanza(sessione, FonteFinta(), fd)
    assert len(fd.chiamate) == 1
    assert sessione.get(Partita, 1).giornata is None


def test_errore_football_data_la_giornata_si_riprova(sessione):
    from ammonizioni.fonti.base import ErroreFonte

    data = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    _salva(sessione, partita_dati(1, data, stagione=2025, giornata=None))
    sessione.get(Partita, 1).statistiche_scaricate = True
    repo.scrivi_impostazione(sessione, "arbitri_collegati", [2025])
    sessione.commit()

    class Rotto(FonteFdStagioni):
        def arbitri(self, codice, dal, al):
            self.chiamate.append(codice)
            raise ErroreFonte("giu'")

    fd = Rotto([])
    r = storico.avanza(sessione, FonteFinta(), fd)
    assert r.completo is False
    assert not repo.leggi_impostazione(sessione, "giornate_collegate")


def test_salva_partita_non_cancella_la_giornata_con_none(sessione):
    data = datetime(2026, 2, 1, 18, 0, tzinfo=timezone.utc)
    _salva(sessione, partita_dati(1, data, giornata=9))
    _salva(sessione, partita_dati(1, data, giornata=None))  # ESPN non la da'
    assert sessione.get(Partita, 1).giornata == 9


def test_stagione_corrente_con_flag_vecchio_ricerca_la_giornata_una_volta_ancora(sessione):
    """Il flag `giornate_collegate` era gia' segnato per la stagione corrente: il flag nuovo
    (`giornate_collegate_v2`) fa ripetere il passo una volta sola."""
    from ammonizioni.config import STAGIONE_CORRENTE
    from ammonizioni.fonti.football_data import ArbitroPartita

    data = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)
    _salva(sessione, partita_dati(1, data, stagione=STAGIONE_CORRENTE, giornata=None))
    sessione.get(Partita, 1).statistiche_scaricate = True
    repo.scrivi_impostazione(sessione, "arbitri_collegati", [STAGIONE_CORRENTE])
    repo.scrivi_impostazione(sessione, "giornate_collegate", [STAGIONE_CORRENTE])
    repo.scrivi_impostazione(
        sessione, "arbitri_ricollegati_il", {"135": datetime.now(timezone.utc).isoformat()}
    )
    sessione.commit()
    fd = FonteFdStagioni([
        ArbitroPartita(data, "Juventus FC", "FC Internazionale Milano", 1, "Davide Massa", 14)
    ])
    storico.avanza(sessione, FonteFinta(), fd)
    assert len(fd.chiamate) == 1
    assert sessione.get(Partita, 1).giornata == 14
    assert repo.leggi_impostazione(sessione, "giornate_collegate_v2") == [STAGIONE_CORRENTE]
    storico.avanza(sessione, FonteFinta(), fd)
    assert len(fd.chiamate) == 1
