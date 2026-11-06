"""Dati di prova nel DB: 2 squadre, 6 partite passate con presenze, un arbitro, un derby,
una partita futura (id 100) con formazione ufficiale."""
from datetime import datetime, timedelta, timezone

from ammonizioni.db.modelli import (
    Arbitro,
    Formazione,
    Giocatore,
    ListaManuale,
    Partita,
    Presenza,
    Squadra,
)

CASA = 1
TRASF = 2
PARTITA_FUTURA = 100
DATA_FUTURA = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)
INIZIO = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)

# (id, nome, ruolo, griglia)
GIOCATORI = {
    CASA: [(11, "Portiere Casa", "G", "1:1"), (12, "Terzino Casa", "D", "2:1"),
           (13, "Centrocampista Casa", "M", "3:1"), (14, "Punta Casa", "F", "4:1")],
    TRASF: [(21, "Portiere Trasf", "G", "1:1"), (22, "Terzino Trasf", "D", "2:1"),
            (23, "Centrocampista Trasf", "M", "3:1"), (24, "Punta Trasf", "F", "4:1")],
}


# panchinari: (id, nome, ruolo, squadra, partite in cui entrano tra le 6 passate)
PANCHINARI = [
    (15, "Punta Riserva Casa", "F", CASA, (1, 2, 3, 4, 6)),
    (16, "Terzo Portiere Casa", "G", CASA, ()),
    (17, "Difensore Mai Casa", "D", CASA, ()),
    (25, "Mediano Riserva Trasf", "M", TRASF, (2, 4, 5)),
]


def popola_panchina(s, *, salvata=True) -> None:
    """Dopo `popola`: panchinari in distinta nelle 6 partite passate (entrati 20 minuti dove
    indicato, un giallo dalla panchina per il 25 nella partita 3) e, con `salvata`, la
    panchina della partita futura salvata con le ufficiali. Quote 1X2: Casa favorita."""
    for gid, nome, ruolo, _, _ in PANCHINARI:
        s.add(Giocatore(id=gid, nome=nome, ruolo=ruolo))
    s.flush()
    for i in range(1, 7):
        for gid, _, _, sq, entra in PANCHINARI:
            s.add(Presenza(
                partita_id=i, giocatore_id=gid, squadra_id=sq, titolare=False, ruolo=None,
                minuti=20 if i in entra else 0, falli_commessi=1 if i in entra else 0,
                gialli=1 if (gid == 25 and i == 3) else 0,
            ))
        # la punta titolare di casa esce al 70' (sostituita)
        s.get(Presenza, (i, 14)).minuti = 70
    futura = s.get(Partita, PARTITA_FUTURA)
    futura.prob_casa, futura.prob_pareggio, futura.prob_trasferta = 0.55, 0.25, 0.20
    if salvata:
        for gid, _, _, sq, _ in PANCHINARI:
            s.add(Formazione(partita_id=PARTITA_FUTURA, squadra_id=sq, giocatore_id=gid,
                             tipo="panchina"))
    s.flush()


def popola(s, *, con_formazione=True, con_arbitro=True) -> None:
    s.add_all([Squadra(id=CASA, nome="Casa FC"), Squadra(id=TRASF, nome="Trasferta FC")])
    for lista in GIOCATORI.values():
        for gid, nome, ruolo, _ in lista:
            s.add(Giocatore(id=gid, nome=nome, ruolo=ruolo))
    s.add(Arbitro(id=1, nome_normalizzato="rossi", nome_visualizzato="Rossi"))
    s.add(ListaManuale(tipo="derby", squadra_a_id=TRASF, squadra_b_id=CASA))
    s.flush()

    for i in range(1, 7):
        casa, trasf = (CASA, TRASF) if i % 2 else (TRASF, CASA)
        s.add(
            Partita(
                id=i, data_utc=INIZIO + timedelta(days=7 * i), competizione_id=135,
                stagione=2026, giornata=i, casa_id=casa, trasferta_id=trasf,
                arbitro_id=1 if con_arbitro else None, gol_casa=1, gol_trasferta=1,
                stato="FT", stato_formazioni="ufficiali", statistiche_scaricate=True,
            )
        )
        s.flush()
        for sq, lista in GIOCATORI.items():
            for gid, _, ruolo, griglia in lista:
                s.add(
                    Presenza(
                        partita_id=i, giocatore_id=gid, squadra_id=sq, titolare=True,
                        ruolo=ruolo, griglia=griglia, minuti=90,
                        gialli=1 if (gid % 2 == 0 and i % 2 == 0) else 0,
                        falli_commessi=2, falli_subiti=1, voto=6.0,
                    )
                )
    s.add(
        Partita(
            id=PARTITA_FUTURA, data_utc=DATA_FUTURA, competizione_id=135, stagione=2026,
            giornata=7, casa_id=CASA, trasferta_id=TRASF,
            arbitro_id=1 if con_arbitro else None, stato="NS",
            stato_formazioni="ufficiali" if con_formazione else "probabili",
        )
    )
    s.flush()
    if con_formazione:
        for sq, lista in GIOCATORI.items():
            for gid, _, _, griglia in lista:
                s.add(
                    Formazione(
                        partita_id=PARTITA_FUTURA, squadra_id=sq, giocatore_id=gid,
                        tipo="ufficiale", griglia=griglia,
                    )
                )
    s.flush()
