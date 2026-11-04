import itertools
from datetime import datetime, timedelta, timezone

from ammonizioni.motore.tipi import MedieCampionato, MedieRuolo, RigaPresenza

_contatore = itertools.count(1)
_INIZIO = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)


def riga(**kw) -> RigaPresenza:
    """RigaPresenza con valori di default; `data` cresce a ogni chiamata."""
    n = next(_contatore)
    valori = dict(
        partita_id=n,
        data=_INIZIO + timedelta(days=n),
        stagione=2026,
        competizione_id=135,
        squadra_id=1,
        avversario_id=2,
        minuti=90,
        gialli=0,
        rossi=0,
        falli_commessi=1,
        falli_subiti=1,
        dribbling_tentati=0,
        dribbling_riusciti=0,
        tiri=0,
        gol=0,
        assist=0,
        voto=6.0,
        titolare=True,
        rivalita=False,
    )
    valori.update(kw)
    return RigaPresenza(**valori)


def medie_standard() -> MedieCampionato:
    return MedieCampionato(
        gialli_partita=4.2,
        falli_partita=25.0,
        per_ruolo={
            "D": MedieRuolo(0.20, 1.4, 1.0, 0.5, 0.10, 6.1),
            "M": MedieRuolo(0.22, 1.3, 1.2, 1.0, 0.20, 6.2),
            "F": MedieRuolo(0.12, 1.1, 1.5, 1.8, 0.40, 6.2),
            "G": MedieRuolo(0.03, 0.1, 0.1, 0.0, 0.0, 6.2),
        },
    )
