import logging
from datetime import date, datetime, timezone

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
from ammonizioni.giocate.registro import aggiungi_giocata


def conta_presenze_scaricate(s) -> int:
    """Numero di partite con statistiche effettivamente salvate."""
    return len({p.partita_id for p in s.scalars(select(Presenza))})


def test_limite_a_meta_job_salva_il_parziale(sessione):
    fonte = FonteFinta(partite_ft=5, limite_dopo=3)  # la 4ª chiamata solleva LimiteSuperato
    r = notturno.esegui(sessione, fonte)
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
    r = notturno.esegui(sessione, fonte)
    assert r.completo is True
    assert r.richieste_usate == 4
    assert r.partite_aggiornate == 3
    assert conta_presenze_scaricate(sessione) == 3


def test_secondo_giro_non_riscarica(sessione):
    notturno.esegui(sessione, FonteFinta(partite_ft=3))
    fonte = FonteFinta(partite_ft=3)
    r = notturno.esegui(sessione, fonte)
    assert r.completo is True
    assert r.partite_aggiornate == 0
    assert [c[0] for c in fonte.chiamate] == ["partite"]


def test_partita_con_errore_saltata_le_altre_scaricate(sessione, caplog):
    fonte = FonteFinta(partite_ft=3, errori={2})
    with caplog.at_level(logging.WARNING, logger="ammonizioni.caricamento.notturno"):
        r = notturno.esegui(sessione, fonte)
    assert r.completo is True
    assert r.partite_aggiornate == 2
    assert sessione.get(Partita, 2).statistiche_scaricate is False
    assert sessione.get(Partita, 1).statistiche_scaricate is True
    assert sessione.get(Partita, 3).statistiche_scaricate is True
    avvisi = [x for x in caplog.records if x.levelno >= logging.WARNING]
    assert len(avvisi) == 1
    assert "2" in avvisi[0].getMessage()


def test_calendario_crea_squadre_arbitro_e_non_resetta_le_statistiche(sessione):
    fonte = FonteFinta(partite_ft=1)
    notturno.aggiorna_calendario(sessione, fonte)
    assert {q.nome for q in sessione.scalars(select(Squadra))} == {"Casa 1", "Inter"}
    assert sessione.scalars(select(Arbitro)).one().nome_normalizzato == "doveri"
    assert sessione.get(Partita, 1).arbitro_id is not None
    notturno.scarica_statistiche_giocate(sessione, fonte)
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
    notturno.esegui(sessione, FonteFinta(partite_ft=1))
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
    notturno.esegui(sessione, FonteFinta(partite_ft=1))
    assert sessione.get(Giocata, giocata.id).esito == "vinta"