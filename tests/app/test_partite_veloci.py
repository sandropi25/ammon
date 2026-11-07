"""prossime_partite: il badge "partita calda" con query raggruppate deve dare gli stessi
risultati del vecchio calcolo (carica_dati per partita), con poche query."""
from datetime import datetime, timedelta, timezone

import ayuda_app  # noqa: F401  (aggiunge app/ e tests/motore a sys.path)
import componenti
from db_prova import PARTITA_FUTURA, popola
from sqlalchemy import event, select

from ammonizioni.db.modelli import (
    Arbitro, Giocatore, ListaManuale, Partita, Presenza, Squadra,
)
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.pesi import carica_pesi

ORA = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


def _scenario(s):
    popola(s)  # partita 100: derby Casa-Trasferta, arbitro Rossi
    s.add_all([Squadra(id=i, nome=f"Squadra {i}") for i in (3, 4, 5, 6, 7, 8)])
    s.add(Arbitro(id=2, nome_normalizzato="severo", nome_visualizzato="Severo"))
    for i in (3, 4):
        s.add(Giocatore(id=i * 10, nome=f"Giocatore {i}", ruolo="D"))
    s.flush()
    # l'arbitro Severo: 10 partite passate piene di gialli
    for k in range(10):
        pid = 300 + k
        s.add(Partita(
            id=pid, data_utc=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=3 * k),
            competizione_id=135, stagione=2026, giornata=k, casa_id=3 if k % 2 else 4,
            trasferta_id=4 if k % 2 else 3, arbitro_id=2, gol_casa=1, gol_trasferta=1,
            stato="FT", stato_formazioni="ufficiali", statistiche_scaricate=True,
        ))
        s.flush()
        for sq, gid in ((3, 30), (4, 40)):
            s.add(Presenza(partita_id=pid, giocatore_id=gid, squadra_id=sq, titolare=True,
                           ruolo="D", minuti=90, gialli=5, falli_commessi=20, falli_subiti=1))
    s.add(ListaManuale(tipo="campo_caldo", squadra_a_id=7))
    s.flush()

    def futura(pid, giorni, casa, trasf, arbitro):
        s.add(Partita(
            id=pid, data_utc=ORA + timedelta(days=giorni), competizione_id=135, stagione=2026,
            giornata=8, casa_id=casa, trasferta_id=trasf, arbitro_id=arbitro, stato="NS",
        ))

    futura(201, 1, 3, 4, 2)        # arbitro severo, niente liste
    futura(202, 1, 5, 6, None)     # tranquilla, senza arbitro
    futura(203, 2, 7, 8, None)     # campo caldo (casa 7)
    futura(204, 2, 5, 6, 1)        # arbitro Rossi (pochi gialli)
    s.flush()


def _vecchio(s, partite):
    pesi = carica_pesi(s)
    return {p.id: componenti.e_partita_calda(carica_dati(s, p.id), pesi) for p in partite}


def test_calde_raggruppate_uguali_al_calcolo_per_partita(sessione):
    _scenario(sessione)
    righe = componenti.prossime_partite(sessione, ORA, giorni=7)
    partite = sessione.execute(select(Partita).where(Partita.data_utc >= ORA)).scalars().all()
    atteso = _vecchio(sessione, partite)
    assert {r.id: r.calda for r in righe} == atteso
    # lo scenario copre i tre motivi (derby, campo caldo, arbitro) e il caso tranquillo
    assert atteso[PARTITA_FUTURA] and atteso[203] and atteso[201]
    assert not atteso[202] and not atteso[204]
    assert {r.id: r.arbitro for r in righe}[201] == "Severo"
    assert {r.id: r.arbitro for r in righe}[202] is None


def test_calde_con_statistiche_fra_le_partite_della_finestra(sessione):
    """Una partita con statistiche fra due partite elencate: le medie vanno calcolate con il
    "prima di" di ogni partita, come nel vecchio calcolo."""
    _scenario(sessione)
    sessione.add(Partita(
        id=500, data_utc=ORA + timedelta(days=1, hours=12), competizione_id=135, stagione=2026,
        giornata=8, casa_id=5, trasferta_id=6, gol_casa=0, gol_trasferta=0, stato="FT",
        statistiche_scaricate=True,
    ))
    sessione.flush()
    sessione.add(Presenza(partita_id=500, giocatore_id=30, squadra_id=3, titolare=True,
                          ruolo="D", minuti=90, gialli=40, falli_commessi=200, falli_subiti=1))
    sessione.flush()
    righe = componenti.prossime_partite(sessione, ORA, giorni=7)
    partite = sessione.execute(
        select(Partita).where(Partita.data_utc >= ORA, Partita.stato == "NS")
    ).scalars().all()
    assert {r.id: r.calda for r in righe if r.id != 500} == _vecchio(sessione, partite)


def test_prossime_partite_poche_query(sessione):
    _scenario(sessione)
    conteggio = []
    event.listen(sessione.get_bind(), "before_cursor_execute", lambda *a: conteggio.append(1))
    componenti.prossime_partite(sessione, ORA, giorni=7)
    # prima ~15 query per partita; ora un numero fisso che non cresce con le partite
    # (13: c'è anche l'impostazione delle immagini ESPN, letta una volta per tutte;
    # +9 per la media della partita e dell'arbitro sulle schede, sempre raggruppate)
    assert len(conteggio) <= 22
