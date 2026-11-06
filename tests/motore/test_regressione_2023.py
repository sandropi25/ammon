"""La stagione 2023 (solo calendario, cartellini totali e arbitri) non cambia il modello:
le classifiche della Serie A restano identiche, anche se l'arbitro ha tante partite 2023."""
from datetime import datetime, timedelta, timezone

from db_prova import CASA, PARTITA_FUTURA, TRASF, popola

from ammonizioni.db.modelli import Partita
from ammonizioni.motore.dati import carica_dati
from ammonizioni.motore.mercati import MercatoAmmonizioni


def _fotografia(s):
    dati = carica_dati(s, PARTITA_FUTURA)
    a = dati.arbitro
    classifica = MercatoAmmonizioni().classifica(s, PARTITA_FUTURA)
    return (
        None if a is None else (
            a.nome, a.partite, a.gialli_medi, a.falli_medi, dict(a.gialli_medi_con)
        ),
        [
            (c.giocatore_id, c.probabilita, c.valore, tuple(f.valore for f in c.fattori))
            for c in classifica
        ],
        dati.medie,
    )


def test_classifica_serie_a_identica_con_la_stagione_2023(sessione):
    popola(sessione)
    prima = _fotografia(sessione)
    assert prima[0] is not None and prima[1]

    # 30 partite 2023 dello stesso arbitro e delle stesse squadre, molto nervose, con i soli
    # totali (nessuna presenza, statistiche non scaricate)
    for i in range(30):
        sessione.add(Partita(
            id=900 + i, data_utc=datetime(2023, 9, 1, tzinfo=timezone.utc) + timedelta(days=7 * i),
            competizione_id=135, stagione=2023, giornata=i + 1,
            casa_id=CASA if i % 2 else TRASF, trasferta_id=TRASF if i % 2 else CASA,
            arbitro_id=1, gol_casa=0, gol_trasferta=0, stato="FT",
            gialli_totali=9, rossi_totali=2, falli_totali=40, statistiche_scaricate=False,
        ))
    sessione.flush()

    assert _fotografia(sessione) == prima
