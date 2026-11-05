"""Pagina Dettaglio: un solo carica_dati, extra per candidato con query raggruppate e stessi
valori delle vecchie funzioni per singolo giocatore."""
import ayuda_app  # noqa: F401  (aggiunge app/ e tests/motore a sys.path)
import componenti
from db_prova import CASA, GIOCATORI, PARTITA_FUTURA, TRASF, popola
from sqlalchemy import event, select

from ammonizioni.db.modelli import Giocatore, Partita, Presenza
from ammonizioni.motore.mercati import MercatoAmmonizioni


def _stat_vecchia(s, giocatore_id, stagione, prima_di):
    righe = s.execute(
        select(Presenza).join(Partita, Partita.id == Presenza.partita_id).where(
            Presenza.giocatore_id == giocatore_id,
            Partita.data_utc < prima_di,
            Partita.stagione.in_((stagione, stagione - 1, stagione - 2)),
        )
    ).scalars().all()
    minuti = sum(r.minuti for r in righe)
    if minuti <= 0:
        return {"minuti": 0}
    return {
        "minuti": minuti,
        "gialli90": sum(r.gialli for r in righe) / minuti * 90,
        "falli90": sum(r.falli_commessi for r in righe) / minuti * 90,
        "falli_subiti90": sum(r.falli_subiti for r in righe) / minuti * 90,
        "dribbling90": sum(r.dribbling_tentati for r in righe) / minuti * 90,
    }


def _storia_vecchia(s, giocatore_id, avversaria, prima_di):
    righe = s.execute(
        select(Presenza).join(Partita, Partita.id == Presenza.partita_id).where(
            Presenza.giocatore_id == giocatore_id,
            Presenza.minuti > 0,
            Presenza.squadra_id != avversaria,
            Partita.data_utc < prima_di,
            (Partita.casa_id == avversaria) | (Partita.trasferta_id == avversaria),
        )
    ).scalars().all()
    return len(righe), sum(r.gialli for r in righe)


def test_statistiche_e_storia_batch_uguali_alle_singole(sessione):
    popola(sessione)
    quando = sessione.get(Partita, PARTITA_FUTURA).data_utc
    ids = {g[0] for lista in GIOCATORI.values() for g in lista} | {9999}  # 9999: senza presenze
    batch = componenti.statistiche_90_batch(sessione, ids, 2026, quando)
    for gid in ids:
        assert batch[gid] == _stat_vecchia(sessione, gid, 2026, quando)
        assert componenti.statistiche_90(sessione, gid, 2026, quando) == batch[gid]
    coppie = {(gid, avv) for gid in ids for avv in (CASA, TRASF)}
    storie = componenti.storia_contro_batch(sessione, coppie, quando)
    for gid, avv in coppie:
        assert storie[(gid, avv)] == _storia_vecchia(sessione, gid, avv, quando)
    assert storie[(13, TRASF)][0] == 6  # sei precedenti, tutti contro la Trasferta


def test_pagina_dettaglio_un_solo_carica_dati_e_poche_query(sessione, monkeypatch):
    popola(sessione)
    chiamate = []
    originale = componenti.carica_dati
    monkeypatch.setattr(componenti, "carica_dati", lambda *a, **k: chiamate.append(1) or originale(*a, **k))
    conteggio = []
    event.listen(sessione.get_bind(), "before_cursor_execute", lambda *a: conteggio.append(1))
    pagina = componenti.carica_pagina_dettaglio(sessione, PARTITA_FUTURA)
    assert len(chiamate) == 1
    assert len(pagina.dettaglio.candidati) == 6  # senza i due portieri
    assert set(pagina.extra) == {c.giocatore_id for c in pagina.dettaglio.candidati}
    # query fisse: non crescono col numero di candidati (prima ~5 per candidato)
    assert len(conteggio) <= 40
    assert componenti.carica_pagina_dettaglio(sessione, 424242) is None


def test_applica_quote_uguale_alla_classifica_con_quote(sessione):
    popola(sessione)
    quote = {12: 3.0, 22: 2.5}
    senza = componenti.carica_pagina_dettaglio(sessione, PARTITA_FUTURA).dettaglio.candidati
    atteso = MercatoAmmonizioni().classifica(sessione, PARTITA_FUTURA, quote=quote)
    assert componenti.applica_quote(senza, quote) == atteso
    assert componenti.applica_quote(senza, {}) == senza
