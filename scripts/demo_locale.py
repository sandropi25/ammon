"""Database SQLite di prova con dati dimostrativi (inventati) per vedere la grafica in locale.

Uso:
    python scripts/demo_locale.py [percorso.db]

Senza argomento crea il file nella cartella temporanea del sistema (mai ammonizioni.db
nella radice del progetto). Stampa i comandi PowerShell per avviare l'app su quel DB.
Squadre e arbitri hanno nomi veri o verosimili, i giocatori sono inventati."""
from __future__ import annotations

import random
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from ammonizioni.config import STAGIONE_CORRENTE  # noqa: E402
from ammonizioni.db.modelli import (  # noqa: E402
    Arbitro, Formazione, Giocata, Giocatore, Partita, Presenza, Squadra, UltimoAggiornamento,
)
from ammonizioni.db.sessione import apri  # noqa: E402

SERIE_A, LIGA = 135, 140
SQUADRE = {
    SERIE_A: ["Inter", "Milan", "Juventus", "Napoli", "Roma", "Lazio", "Atalanta", "Fiorentina"],
    LIGA: ["Real Madrid", "Barcelona", "Atlético de Madrid", "Sevilla"],
}
ARBITRI = {
    SERIE_A: ["Marco Severi", "Luca Bianchi", "Paolo Mariani", "Andrea Colombo"],
    LIGA: ["Jorge Martínez Ruiz", "Pablo Ortega"],
}
NOMI = ["Marco", "Luca", "Davide", "Simone", "Matteo", "Andrea", "Nicolò", "Federico", "Lorenzo",
        "Alessio", "Pablo", "Iker", "Sergio", "Álvaro", "Hugo", "Raúl"]
COGNOMI = ["Rinaldi", "Ferraro", "Galli", "Conti", "Marchetti", "Barbieri", "Fontana", "Sala",
           "Moretti", "D'Angelo", "Caruso", "Lombardi", "García", "Navarro", "Romero", "Iglesias",
           "Serrano", "Vidal", "Castro", "Ortiz"]
# ruolo e posizione nella griglia (riga:colonna) degli 11 titolari
SCHIERAMENTO = [("G", "1:1"), ("D", "2:1"), ("D", "2:2"), ("D", "2:3"), ("D", "2:4"),
                ("M", "3:1"), ("M", "3:2"), ("M", "3:3"), ("F", "4:1"), ("F", "4:2"), ("F", "4:3")]
PROB_GIALLO = {"G": 0.02, "D": 0.16, "M": 0.2, "F": 0.08}
# panchina di ogni squadra: (ruolo, minuti possibili quando è in distinta; 0 = non entra)
PANCHINA = [("F", (0, 15, 25, 30)), ("M", (0, 0, 20, 30)), ("D", (0, 0, 0, 0, 20)), ("G", (0,))]


def popola_demo(url: str, adesso: datetime | None = None) -> None:
    rnd = random.Random(2026)
    adesso = (adesso or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    with apri(url) as s:
        squadre: dict[int, list[int]] = {}
        rose: dict[int, list[tuple[int, str, str]]] = {}
        sid, gid = 1, 1000
        for camp, nomi in SQUADRE.items():
            squadre[camp] = []
            for nome in nomi:
                s.add(Squadra(id=sid, nome=nome))
                squadre[camp].append(sid)
                rose[sid] = []
                for ruolo, griglia in SCHIERAMENTO:
                    s.add(Giocatore(id=gid, nome=f"{rnd.choice(NOMI)} {rnd.choice(COGNOMI)}", ruolo=ruolo))
                    rose[sid].append((gid, ruolo, griglia))
                    gid += 1
                sid += 1
        # panchinari (generatore a parte: il resto dei dati dimostrativi non cambia)
        rnd_p = random.Random(99)
        panchine: dict[int, list[tuple[int, str, tuple[int, ...]]]] = {}
        for sq in rose:
            panchine[sq] = []
            for ruolo, minuti_possibili in PANCHINA:
                s.add(Giocatore(id=gid, nome=f"{rnd_p.choice(NOMI)} {rnd_p.choice(COGNOMI)}",
                                ruolo=ruolo))
                panchine[sq].append((gid, ruolo, minuti_possibili))
                gid += 1
        arbitri: dict[int, list[int]] = {}
        aid = 1
        for camp, nomi in ARBITRI.items():
            arbitri[camp] = []
            for nome in nomi:
                s.add(Arbitro(id=aid, nome_normalizzato=nome.lower(), nome_visualizzato=nome))
                arbitri[camp].append(aid)
                aid += 1
        # nessuna lista manuale: Inter-Milan, Roma-Lazio e gli altri derby sono riconosciuti dai
        # nomi, il campo caldo del Napoli dai cartellini della stagione scorsa (vedi sotto)
        inter, milan, roma, lazio = (squadre[SERIE_A][i] for i in (0, 1, 4, 5))
        napoli = squadre[SERIE_A][3]
        s.flush()

        # storico: 8 giornate già giocate per campionato (tutti contro tutti, a rotazione),
        # numerate 1-8 con i risultati; le prossime partite sono la giornata 9 (e 10) del Calendario
        pid = 1
        passate: list[int] = []  # di Serie A, per le giocate dimostrative
        panchina: list[int] = []  # partite con un ammonito dalla panchina
        for camp, ids in squadre.items():
            for giornata in range(1, 9):
                quando = adesso - timedelta(days=7 * (9 - giornata), hours=rnd.randint(0, 30))
                ordine = ids[:]
                rnd.shuffle(ordine)
                for casa, trasf in zip(ordine[::2], ordine[1::2]):
                    severo = rnd.random() < 0.3
                    s.add(Partita(
                        id=pid, data_utc=quando, competizione_id=camp, stagione=STAGIONE_CORRENTE,
                        giornata=giornata, casa_id=casa, trasferta_id=trasf,
                        arbitro_id=arbitri[camp][0] if severo else rnd.choice(arbitri[camp]),
                        gol_casa=rnd.randint(0, 3), gol_trasferta=rnd.randint(0, 3), stato="FT",
                        stato_formazioni="ufficiali", statistiche_scaricate=True,
                    ))
                    s.flush()
                    for sq in (casa, trasf):
                        for g, ruolo, griglia in rose[sq]:
                            spinta = 1.8 if severo else 1.0
                            s.add(Presenza(
                                partita_id=pid, giocatore_id=g, squadra_id=sq, titolare=True,
                                ruolo=ruolo, griglia=griglia, minuti=rnd.choice((90, 90, 90, 75, 62)),
                                gialli=int(rnd.random() < PROB_GIALLO[ruolo] * spinta),
                                falli_commessi=rnd.randint(0, 4 if ruolo in "DM" else 2),
                                falli_subiti=rnd.randint(0, 3), dribbling_tentati=rnd.randint(0, 4),
                            ))
                        for g, ruolo, minuti_possibili in panchine[sq]:
                            # in distinta: chi entra gioca qualche minuto (probabili subentranti)
                            entrato = rnd_p.choice(minuti_possibili)
                            s.add(Presenza(
                                partita_id=pid, giocatore_id=g, squadra_id=sq, titolare=False,
                                minuti=entrato,
                                gialli=int(entrato > 0 and rnd_p.random() < 0.12),
                                falli_commessi=rnd_p.randint(0, 2) if entrato else 0,
                            ))
                    if giornata == 8 and camp == SERIE_A and len(panchina) < 2:
                        # ammonito dalla panchina (0 minuti): conta nei cartellini del Calendario
                        s.add(Giocatore(id=9000 + len(panchina), nome=f"Riserva {len(panchina) + 1}",
                                        ruolo="M"))
                        s.flush()
                        s.add(Presenza(
                            partita_id=pid, giocatore_id=9000 + len(panchina), squadra_id=casa,
                            titolare=False, ruolo="M", minuti=0, gialli=1,
                            rossi=len(panchina),  # la seconda riserva ha anche un rosso
                        ))
                        panchina.append(pid)
                    if camp == SERIE_A:
                        passate.append(pid)
                    pid += 1

        # stagione scorsa: 16 partite in casa del Napoli molto nervose (almeno 9 gialli della
        # sola squadra di casa): il Napoli risulta "campo caldo" in automatico
        altri = [q for q in squadre[SERIE_A] if q != napoli]
        for k in range(16):
            ospite = altri[k % len(altri)]
            s.add(Partita(
                id=pid, data_utc=adesso - timedelta(days=330 - 7 * k), competizione_id=SERIE_A,
                stagione=STAGIONE_CORRENTE - 1, giornata=k + 1, casa_id=napoli,
                trasferta_id=ospite, arbitro_id=rnd.choice(arbitri[SERIE_A]), gol_casa=1,
                gol_trasferta=1, stato="FT", stato_formazioni="ufficiali",
                statistiche_scaricate=True,
            ))
            s.flush()
            for sq in (napoli, ospite):
                for n, (g, ruolo, griglia) in enumerate(rose[sq]):
                    s.add(Presenza(
                        partita_id=pid, giocatore_id=g, squadra_id=sq, titolare=True, ruolo=ruolo,
                        griglia=griglia, minuti=90,
                        gialli=int(sq == napoli and 1 <= n <= 9) or int(rnd.random() < 0.1),
                        falli_commessi=rnd.randint(0, 3), falli_subiti=rnd.randint(0, 3),
                    ))
            pid += 1

        # prossime partite: Serie A in 4 giorni, Liga in 2, alcune con formazioni ufficiali
        future = [
            (SERIE_A, inter, milan, 1, 19, 45, True), (SERIE_A, roma, lazio, 1, 17, 0, False),
            (SERIE_A, squadre[SERIE_A][2], squadre[SERIE_A][3], 2, 19, 45, True),
            (SERIE_A, squadre[SERIE_A][6], squadre[SERIE_A][7], 2, 14, 0, False),
            (SERIE_A, milan, squadre[SERIE_A][2], 4, 19, 45, False),
            (SERIE_A, napoli, squadre[SERIE_A][7], 4, 11, 30, False),  # in casa del Napoli
            # un derby lontano: nella sezione "resto della stagione" delle Partite calde
            (SERIE_A, milan, inter, 20, 20, 45, False),
            (LIGA, squadre[LIGA][0], squadre[LIGA][1], 2, 20, 0, True),
            (LIGA, squadre[LIGA][2], squadre[LIGA][3], 3, 18, 30, False),
        ]
        oggi = adesso.date()
        prime: list[int] = []
        for camp, casa, trasf, giorni, ora, minuti, ufficiali in future:
            giorno = oggi + timedelta(days=giorni)
            quando = datetime(giorno.year, giorno.month, giorno.day, ora, minuti, tzinfo=timezone.utc)
            s.add(Partita(
                id=pid, data_utc=quando, competizione_id=camp, stagione=STAGIONE_CORRENTE,
                giornata=9 if giorni < 4 else 10, casa_id=casa, trasferta_id=trasf,
                arbitro_id=None if giorni == 4 else rnd.choice(arbitri[camp]), stato="NS",
                stato_formazioni="ufficiali" if ufficiali else "probabili",
            ))
            s.flush()
            for sq in (casa, trasf):
                for g, _, griglia in rose[sq]:
                    tipi = ("probabile", "ufficiale") if ufficiali else ("probabile",)
                    for tipo in tipi:
                        s.add(Formazione(partita_id=pid, squadra_id=sq, giocatore_id=g,
                                         tipo=tipo, griglia=griglia))
                if ufficiali:  # con le ufficiali arriva anche la panchina in distinta
                    for g, _, _ in panchine[sq]:
                        s.add(Formazione(partita_id=pid, squadra_id=sq, giocatore_id=g,
                                         tipo="panchina"))
            if (casa, trasf) == (inter, milan):
                # quote 1X2 (probabilità implicite): il Milan è sfavorito
                partita = s.get(Partita, pid)
                partita.prob_casa, partita.prob_pareggio, partita.prob_trasferta = 0.52, 0.26, 0.22
            prime.append(pid)
            pid += 1

        # qualche giocata registrata
        esiti = ["vinta", "persa", "vinta", "rimborsata", "persa", "vinta"]
        for i, partita in enumerate(passate[-6:]):
            p = s.get(Partita, partita)
            g = rose[p.casa_id][5 + i % 3][0]
            s.add(Giocata(data=p.data_utc.date(), partita_id=partita, giocatore_id=g,
                          fonte=("io", "modello", "Luca")[i % 3], quota=round(2.2 + 0.35 * i, 2),
                          puntata=10.0, esito=esiti[i]))
        s.add(Giocata(data=oggi, partita_id=prime[0], giocatore_id=rose[inter][6][0], fonte="io",
                      quota=2.6, puntata=5.0, esito="in_attesa"))
        s.add(UltimoAggiornamento(job="notte", quando_utc=adesso - timedelta(hours=7), completo=True))

        # biografie (inventate, come i giocatori) per i giocatori di movimento di alcune squadre:
        # le mostra la Home; il link porta alla voce generica "Calciatore" di Wikipedia
        rnd_b = random.Random(7)
        posizioni = {"D": "Difensore", "M": "Centrocampista", "F": "Attaccante"}
        nazioni = ["Italia", "Spagna", "Argentina", "Brasile", "Francia", "Croazia"]
        for sq in (inter, milan, napoli, squadre[LIGA][0]):
            for g, ruolo, _ in rose[sq][1:]:
                giocatore = s.get(Giocatore, g)
                giocatore.data_nascita = date(rnd_b.randint(1992, 2004), rnd_b.randint(1, 12), rnd_b.randint(1, 28))
                giocatore.nazionalita = rnd_b.choice(nazioni)
                giocatore.altezza_cm = rnd_b.randint(172, 194)
                giocatore.posizione = posizioni[ruolo]
                giocatore.wiki_titolo = giocatore.nome
                giocatore.wiki_url = "https://it.wikipedia.org/wiki/Calciatore"
                giocatore.wiki_estratto = (
                    f"{giocatore.nome} è un calciatore inventato per i dati dimostrativi, "
                    f"{posizioni[ruolo].lower()} di grande temperamento: in campo non si "
                    "risparmia e gli arbitri lo conoscono bene."
                )
                giocatore.bio_aggiornata = adesso


def main() -> None:
    if len(sys.argv) > 1:
        percorso = Path(sys.argv[1]).resolve()
    else:
        percorso = Path(tempfile.gettempdir()) / "cartellino_demo.db"
    if percorso.resolve() == (RADICE / "ammonizioni.db").resolve():
        sys.exit("Non uso il database del progetto: scegli un altro percorso.")
    if percorso.exists():
        percorso.unlink()
    url = f"sqlite:///{percorso.as_posix()}"
    popola_demo(url)
    python = Path(sys.executable)
    print(f"Database dimostrativo creato: {percorso}")
    print()
    print("Avvio (PowerShell, dalla cartella del progetto):")
    print(f'  $env:DATABASE_URL = "{url}"')
    print(f'  & "{python}" -m streamlit run app/Partite.py --server.headless true --server.port 8599')
    print()
    print("Poi apri http://localhost:8599  (tema chiaro: http://localhost:8599/?tema=chiaro)")


if __name__ == "__main__":
    main()
