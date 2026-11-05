from datetime import datetime, timedelta, timezone

import pytest
from conftest import FonteFinta
from sqlalchemy import select

from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra
from ammonizioni.fonti.espn import probabilita_1x2
from ammonizioni.scheduler import pre_partita

INIZIO = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
ADESSO = INIZIO - timedelta(minutes=30)


class FonteConQuote(FonteFinta):
    def __init__(self, quote, **kw):
        super().__init__(**kw)
        self._quote = quote

    def quote_1x2(self, partita_id):
        return self._quote.get(partita_id)


def prepara(s):
    s.add_all([Squadra(id=1, nome="Casa"), Squadra(id=2, nome="Trasferta")])
    s.add_all([Giocatore(id=i, nome=f"G{i}", ruolo="D") for i in range(1, 30)])
    s.add(
        Partita(id=100, data_utc=INIZIO, competizione_id=135, stagione=2026, casa_id=1,
                trasferta_id=2, stato="NS", stato_formazioni="probabili")
    )
    s.flush()


def test_quote_salvate_sulla_partita(sessione):
    prepara(sessione)
    fonte = FonteConQuote({100: (0.5, 0.3, 0.2)})
    pre_partita.esegui(sessione, fonte, ADESSO)
    p = sessione.get(Partita, 100)
    assert (p.prob_casa, p.prob_pareggio, p.prob_trasferta) == (0.5, 0.3, 0.2)


def test_senza_quote_le_colonne_restano_vuote(sessione):
    prepara(sessione)
    pre_partita.esegui(sessione, FonteConQuote({}), ADESSO)
    pre_partita.esegui(sessione, FonteFinta(), ADESSO)  # fonte senza quote_1x2
    p = sessione.get(Partita, 100)
    assert (p.prob_casa, p.prob_pareggio, p.prob_trasferta) == (None, None, None)


def test_probabili_salvate_dal_calcolo_sul_campionato(sessione):
    """Cinque partite di campionato uguali: le probabili salvate sono quel XI, con griglia."""
    prepara(sessione)
    for n in range(1, 6):
        sessione.add(
            Partita(id=n, data_utc=INIZIO - timedelta(days=7 * n), competizione_id=135,
                    stagione=2026, casa_id=1, trasferta_id=2, stato="FT")
        )
        sessione.flush()
        for g in range(1, 12):
            sessione.add(Presenza(partita_id=n, giocatore_id=g, squadra_id=1, titolare=True,
                                  ruolo="D", griglia=f"2:{g}", minuti=90))
    sessione.flush()
    pre_partita.esegui(sessione, FonteFinta(), ADESSO)
    probabili = sessione.scalars(
        select(Formazione).where(Formazione.tipo == "probabile", Formazione.squadra_id == 1)
    ).all()
    assert sorted(f.giocatore_id for f in probabili) == list(range(1, 12))
    assert all(f.griglia and f.griglia.startswith("2:") for f in probabili)


def test_moneyline_americane_in_probabilita_normalizzate():
    corpo = {"odds": [{"homeTeamOdds": {"moneyLine": -150}, "drawOdds": {"moneyLine": 250},
                       "awayTeamOdds": {"moneyLine": 400}}]}
    casa, pareggio, trasferta = probabilita_1x2(corpo)
    assert casa + pareggio + trasferta == pytest.approx(1)
    assert casa > pareggio > trasferta


def test_moneyline_formato_con_close_e_stringhe():
    corpo = {"odds": [{"moneyline": {
        "home": {"close": {"odds": "-120"}}, "draw": {"close": {"odds": "+240"}},
        "away": {"close": {"odds": "EVEN"}},
    }}]}
    assert sum(probabilita_1x2(corpo)) == pytest.approx(1)


@pytest.mark.parametrize(
    "corpo",
    [{}, {"odds": None}, {"odds": []}, {"odds": [{"homeTeamOdds": {"moneyLine": -150}}]},
     {"odds": [{"homeTeamOdds": {"moneyLine": "boh"}, "drawOdds": {"moneyLine": 1},
                "awayTeamOdds": {"moneyLine": 1}}]}],
)
def test_quote_mancanti_o_illeggibili_none(corpo):
    assert probabilita_1x2(corpo) is None
