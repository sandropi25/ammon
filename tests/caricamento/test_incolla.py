"""Formazione ufficiale incollata dall'utente (testo dei giornali) quando ESPN e' in ritardo."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ammonizioni.caricamento import incolla
from ammonizioni.db.modelli import Formazione, Giocatore, Partita, Presenza, Squadra

INIZIO = datetime(2026, 11, 22, 19, 45, tzinfo=timezone.utc)
PASSATA = datetime(2026, 11, 8, 19, 45, tzinfo=timezone.utc)

ATALANTA = [
    (1, "Marco Carnesecchi"), (2, "Raoul Bellanova"), (3, "Giorgio Scalvini"),
    (4, "Sead Kolasinac"), (5, "Davide Zappacosta"), (6, "Franck Kessié"), (7, "Éderson"),
    (8, "Eljif Elmas"), (9, "Charles De Ketelaere"), (10, "Nicola Zalewski"),
    (11, "Nikola Krstovic"), (12, "Lautaro Martínez"),
]
INTER = [(20, "Josep Martínez"), (21, "Lautaro Martínez"), (22, "Pio Esposito"),
         (23, "Salvatore Esposito"), (24, "Alessandro Bastoni")]

TESTO_ATALANTA = (
    "ATALANTA (4-2-3-1): Carnesecchi; Bellanova, Scalvini, Kolasinac, Zappacosta; Kessié, "
    "Ederson; Elmas, De Ketelaere, Zalewski; Krstovic. A disp.: Sportiello, Rowe. All. Sarri"
)


def prepara(s):
    s.add_all([Squadra(id=105, nome="Atalanta"), Squadra(id=110, nome="Internazionale"),
               Squadra(id=999, nome="Altra")])
    s.add_all([Giocatore(id=i, nome=n) for i, n in ATALANTA + INTER[:1] + INTER[2:]])
    s.flush()
    s.add_all([
        Partita(id=1, data_utc=PASSATA, competizione_id=135, stagione=2026, casa_id=105,
                trasferta_id=999, stato="FT", stato_formazioni="ufficiali"),
        Partita(id=2, data_utc=INIZIO, competizione_id=135, stagione=2026, casa_id=105,
                trasferta_id=110, stato="NS", stato_formazioni="probabili"),
    ])
    s.flush()
    # Lautaro (12) ha giocato per l'Atalanta solo in questo test: serve a provare gli omonimi
    for gid, _ in ATALANTA:
        s.add(Presenza(partita_id=1, giocatore_id=gid, squadra_id=105, titolare=True, minuti=90))
    for gid, _ in INTER[:1] + INTER[2:]:
        s.add(Presenza(partita_id=1, giocatore_id=gid, squadra_id=110, titolare=True, minuti=90))
    s.flush()
    return s.get(Partita, 2)


def test_legge_le_linee_del_testo_dei_giornali():
    linee = incolla.leggi_testo(TESTO_ATALANTA)
    assert linee == [
        ["Carnesecchi"], ["Bellanova", "Scalvini", "Kolasinac", "Zappacosta"],
        ["Kessié", "Ederson"], ["Elmas", "De Ketelaere", "Zalewski"], ["Krstovic"],
    ]


@pytest.mark.parametrize("testo", [
    "Carnesecchi\nBellanova, Scalvini, Kolasinac, Zappacosta\nKessié, Ederson\n"
    "Elmas, De Ketelaere, Zalewski\nKrstovic",
    "1 Carnesecchi; 16 Bellanova, 42 Scalvini, 23 Kolasinac, 77 Zappacosta; Kessié, Ederson; "
    "Elmas, De Ketelaere, Zalewski; 90 Krstovic",
    "Atalanta: Carnesecchi; Bellanova, Scalvini, Kolasinac, Zappacosta; Kessié, Ederson; "
    "Elmas, De Ketelaere, Zalewski; Krstovic\nAllenatore: Sarri",
])
def test_altri_formati_comuni(testo):
    assert [len(l) for l in incolla.leggi_testo(testo)] == [1, 4, 2, 3, 1]


def test_riconosce_i_giocatori_della_squadra(sessione):
    partita = prepara(sessione)
    lettura = incolla.riconosci(sessione, partita, 105, TESTO_ATALANTA)
    assert lettura.mancanti == [] and lettura.ambigui == []
    assert [g for g, _ in lettura.titolari] == list(range(1, 12))
    griglie = dict(lettura.titolari)
    assert griglie[1] == "1:1" and griglie[2] == "2:1" and griglie[5] == "2:4"
    assert griglie[6] == "3:1" and griglie[10] == "4:3" and griglie[11] == "5:1"
    assert lettura.pronta


def test_nome_sconosciuto_e_omonimi(sessione):
    partita = prepara(sessione)
    lettura = incolla.riconosci(sessione, partita, 110, "Martinez; Bastoni; Esposito; Rossi")
    assert lettura.mancanti == ["Rossi"]
    # "Martinez" nell'Inter e' solo Josep (Lautaro ha giocato per un'altra squadra);
    # "Esposito" e' ambiguo tra Pio e Salvatore
    assert dict(lettura.titolari)[20] == "1:1" and 24 in dict(lettura.titolari)
    assert [testo for testo, _ in lettura.ambigui] == ["Esposito"]
    assert not lettura.pronta


def test_iniziale_risolve_gli_omonimi(sessione):
    partita = prepara(sessione)
    lettura = incolla.riconosci(sessione, partita, 110, "J. Martinez; P. Esposito")
    assert [g for g, _ in lettura.titolari] == [20, 22]
    lettura = incolla.riconosci(sessione, partita, 110, "Martinez J.; Esposito S.")
    assert [g for g, _ in lettura.titolari] == [20, 23]


def test_scelta_manuale_di_un_ambiguo(sessione):
    partita = prepara(sessione)
    lettura = incolla.riconosci(sessione, partita, 110, "Martinez; Esposito", scelte={"Esposito": 22})
    assert [g for g, _ in lettura.titolari] == [20, 22] and lettura.ambigui == []


def test_salva_una_squadra_alla_volta(sessione):
    partita = prepara(sessione)
    lettura = incolla.riconosci(sessione, partita, 105, TESTO_ATALANTA)
    incolla.salva(sessione, partita, 105, lettura.titolari)
    righe = sessione.scalars(select(Formazione).where(
        Formazione.partita_id == 2, Formazione.tipo == "ufficiale")).all()
    assert len(righe) == 11 and {r.squadra_id for r in righe} == {105}
    assert partita.stato_formazioni == "probabili"  # manca ancora l'Inter

    inter = [(20 + i if i < 5 else 100 + i, f"1:1") for i in range(11)]
    for gid, _ in inter:
        if sessione.get(Giocatore, gid) is None:
            sessione.add(Giocatore(id=gid, nome=f"G{gid}"))
    sessione.flush()
    incolla.salva(sessione, partita, 110, inter)
    assert partita.stato_formazioni == "ufficiali"

    # rincollare l'Atalanta sostituisce solo le sue righe
    incolla.salva(sessione, partita, 105, lettura.titolari[:11])
    assert len(sessione.scalars(select(Formazione).where(
        Formazione.partita_id == 2, Formazione.tipo == "ufficiale")).all()) == 22


def test_salva_rifiuta_una_formazione_incompleta(sessione):
    partita = prepara(sessione)
    with pytest.raises(ValueError):
        incolla.salva(sessione, partita, 105, [(1, "1:1")])


def test_chi_e_gia_riconosciuto_non_rende_ambiguo_un_altro_nome(sessione):
    partita = prepara(sessione)
    # "P. Esposito" e' sicuro: allora "Esposito" puo' essere solo Salvatore
    lettura = incolla.riconosci(sessione, partita, 110, "Martinez; P. Esposito, Esposito")
    assert [g for g, _ in lettura.titolari] == [20, 22, 23] and lettura.ambigui == []
