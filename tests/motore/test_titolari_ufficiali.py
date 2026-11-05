from db_prova import PARTITA_FUTURA, popola
from sqlalchemy import select

from ammonizioni.db.modelli import Formazione, Partita
from ammonizioni.motore.dati import _titolari


def test_con_le_ufficiali_i_titolari_non_cambiano(sessione):
    """Regressione: con formazioni ufficiali il motore usa solo quelle, mai le probabili calcolate."""
    popola(sessione)
    partita = sessione.get(Partita, PARTITA_FUTURA)
    prima = _titolari(sessione, partita, partita.data_utc)
    ufficiali = sessione.scalars(
        select(Formazione.giocatore_id).where(Formazione.tipo == "ufficiale")
    ).all()
    assert sorted(t.giocatore_id for t in prima) == sorted(ufficiali)
    # una probabile diversa non cambia nulla
    sessione.add(
        Formazione(partita_id=PARTITA_FUTURA, squadra_id=1, giocatore_id=12, tipo="probabile")
    )
    sessione.flush()
    assert _titolari(sessione, partita, partita.data_utc) == prima


def test_senza_ufficiali_le_probabili_calcolate_dal_campionato(sessione):
    popola(sessione, con_formazione=False)
    partita = sessione.get(Partita, PARTITA_FUTURA)
    titolari = _titolari(sessione, partita, partita.data_utc)
    assert {t.giocatore_id for t in titolari} == {11, 12, 13, 14, 21, 22, 23, 24}
