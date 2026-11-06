"""Stemmi, colori e numeri di maglia salvati nel database (solo fonti finte)."""
from dataclasses import replace
from datetime import datetime, timezone

from conftest import FonteFinta, partita_dati
from sqlalchemy import create_engine, inspect, text

from ammonizioni.caricamento import notturno, stemmi
from ammonizioni.db import sessione as modulo_sessione
from ammonizioni.db.modelli import Formazione, Partita, Presenza, Squadra
from ammonizioni.fonti.tipi import FormazioneDati, PresenzaDati, StileSquadra
from ammonizioni.scheduler import pre_partita

QUANDO = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
COMO = StileSquadra("https://a.espncdn.com/i/teamlogos/soccer/500/2572.png", "#4169E1", "#FFFFFF")


def test_colonne_aggiunte_a_tabelle_esistenti_in_modo_idempotente(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'vecchio.db'}")
    with engine.begin() as conn:  # vecchia versione: niente stemmi né numeri di maglia
        conn.execute(text("CREATE TABLE squadre (id INTEGER PRIMARY KEY, nome VARCHAR)"))
        conn.execute(text(
            "CREATE TABLE presenze (partita_id INTEGER, giocatore_id INTEGER, squadra_id INTEGER, "
            "PRIMARY KEY (partita_id, giocatore_id))"
        ))
        conn.execute(text(
            "CREATE TABLE formazioni (partita_id INTEGER, squadra_id INTEGER, giocatore_id INTEGER, "
            "tipo VARCHAR, griglia VARCHAR, PRIMARY KEY (partita_id, squadra_id, giocatore_id, tipo))"
        ))
    modulo_sessione.crea_tabelle(engine)
    modulo_sessione.crea_tabelle(engine)  # secondo avvio: nessun errore
    ispettore = inspect(engine)
    assert {"logo_url", "colore", "colore_alt"} <= {c["name"] for c in ispettore.get_columns("squadre")}
    assert "maglia" in {c["name"] for c in ispettore.get_columns("presenze")}
    assert "maglia" in {c["name"] for c in ispettore.get_columns("formazioni")}
    engine.dispose()


def test_calendario_salva_stemma_e_colori_senza_cancellarli(sessione):
    dati = replace(partita_dati(1, QUANDO, casa=(1, "Como")), casa_stile=COMO)
    notturno.salva_partita(sessione, dati)
    sessione.commit()
    como = sessione.get(Squadra, 1)
    assert (como.logo_url, como.colore, como.colore_alt) == (COMO.logo_url, "#4169E1", "#FFFFFF")
    assert sessione.get(Squadra, 2).logo_url is None
    # un calendario successivo senza stemmi non li cancella
    notturno.salva_partita(sessione, partita_dati(1, QUANDO, casa=(1, "Como")))
    sessione.commit()
    sessione.expire_all()
    assert sessione.get(Squadra, 1).logo_url == COMO.logo_url


def _presenza(maglia):
    return PresenzaDati(
        partita_id=1, giocatore_id=7, giocatore_nome="Sette", squadra_id=1, titolare=True,
        ruolo="M", griglia=None, minuti=90, gialli=0, rossi=0, falli_commessi=0, falli_subiti=0,
        dribbling_tentati=0, dribbling_riusciti=0, tiri=0, gol=0, assist=0, voto=None,
        maglia=maglia,
    )


def test_presenza_salva_il_numero_di_maglia_senza_cancellarlo(sessione):
    notturno.salva_partita(sessione, partita_dati(1, QUANDO))
    notturno._salva_presenza(sessione, _presenza(10))
    sessione.commit()
    assert sessione.get(Presenza, (1, 7)).maglia == 10
    notturno._salva_presenza(sessione, _presenza(None))
    sessione.commit()
    sessione.expire_all()
    assert sessione.get(Presenza, (1, 7)).maglia == 10


class FonteConStili(FonteFinta):
    def __init__(self, stili, **kwargs):
        super().__init__(**kwargs)
        self.stili = stili

    def stili_squadre(self):
        return dict(self.stili)


def test_statistiche_salvano_gli_stili_letti_dal_summary(sessione):
    fonte = FonteConStili({11: COMO}, partite_ft=1)
    notturno.aggiorna_calendario(sessione, fonte, 2026)
    assert notturno.scarica_statistiche_partita(sessione, notturno.FonteContata(fonte), 1)
    assert sessione.get(Squadra, 11).colore == "#4169E1"
    # nessuna richiesta in più: calendario e statistiche
    assert [c[0] for c in fonte.chiamate] == ["partite", "statistiche"]


def test_salva_stili_aggiorna_solo_le_squadre_note(sessione):
    sessione.add_all([Squadra(id=1, nome="Como"), Squadra(id=2, nome="Venezia", colore="#000000")])
    sessione.flush()
    cambiate = stemmi.salva_stili(sessione, {
        1: COMO, 2: StileSquadra(None, "#000000", None), 99: COMO,
    })
    assert cambiate == 1  # Venezia era già così, la 99 non esiste
    assert sessione.get(Squadra, 99) is None
    assert sessione.get(Squadra, 1).logo_url == COMO.logo_url


def test_riempimento_una_tantum_dai_calendari(sessione):
    sessione.add_all([Squadra(id=1, nome="Como"), Squadra(id=3, nome="Siviglia")])
    sessione.flush()
    serie_a = [replace(partita_dati(1, QUANDO, casa=(1, "Como")), casa_stile=COMO)]
    liga = [replace(
        partita_dati(2, QUANDO, competizione_id=140, casa=(3, "Siviglia"), trasferta=(4, "Betis")),
        casa_stile=StileSquadra(None, "#D11F26", None),
    )]
    fonte = FonteFinta(calendari={(135, 2026): serie_a, (140, 2026): liga})
    assert stemmi.riempi_stemmi(sessione, fonte, 2026) == 2
    assert fonte.chiamate == [("partite", 135, 2026), ("partite", 140, 2026)]
    assert sessione.get(Squadra, 3).colore == "#D11F26"
    assert sessione.get(Partita, 1) is None  # le partite non si toccano
    assert sessione.get(Squadra, 4) is None


def test_formazione_ufficiale_salva_i_numeri_di_maglia(sessione):
    sessione.add_all([Squadra(id=1, nome="Casa"), Squadra(id=2, nome="Trasferta")])
    sessione.add(Partita(
        id=100, data_utc=QUANDO, competizione_id=135, stagione=2026, casa_id=1, trasferta_id=2,
        stato="NS",
    ))
    sessione.flush()
    formazioni = [
        FormazioneDati(100, 1, [(1, "G1", "D", "2:1")], panchina=[(3, "G3", None)],
                       maglie={1: 4, 3: 22}),
        FormazioneDati(100, 2, [(5, "G5", "D", "2:1")]),
    ]
    pre_partita._salva_ufficiali(sessione, sessione.get(Partita, 100), formazioni)
    sessione.flush()
    assert sessione.get(Formazione, (100, 1, 1, "ufficiale")).maglia == 4
    assert sessione.get(Formazione, (100, 1, 3, "panchina")).maglia == 22
    assert sessione.get(Formazione, (100, 2, 5, "ufficiale")).maglia is None
