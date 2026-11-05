"""Controllo di salute di ESPN: legge una partita di Serie A gia' finita e verifica che ci
siano i campi che `Espn` usa. ESPN e' un'API non ufficiale e la struttura puo' cambiare
senza preavviso: meglio accorgersene con un messaggio chiaro che con dati vuoti."""
from __future__ import annotations

from ammonizioni.fonti.base import ErroreFonte

# Sassuolo-Fiorentina, Serie A, 2 novembre 2026 (finita 4-1): la stessa di tests/dati_prova/espn.
PARTITA_CONTROLLO = 401874963

STATISTICHE_USATE = ("foulsCommitted", "foulsSuffered", "yellowCards", "redCards")


def _nodo(valore) -> dict:
    """Il nodo se e' un oggetto JSON, altrimenti un oggetto vuoto (campo mancante)."""
    return valore if isinstance(valore, dict) else {}


def controlla_struttura(fonte) -> list[str]:
    """Scarica la partita di controllo e restituisce i problemi trovati (lista vuota se la
    struttura e' quella attesa). Non solleva mai: una lettura fallita o una forma
    inattesa dei dati e' un problema da riportare."""
    try:
        return _controlla(fonte)
    except ErroreFonte as errore:
        return [f"partita di controllo {PARTITA_CONTROLLO} non letta: {errore}"]
    except Exception as errore:  # noqa: BLE001 - ESPN puo' cambiare forma in qualsiasi punto
        return [f"struttura inattesa: {errore!r}"]


def _controlla(fonte) -> list[str]:
    corpo = fonte.summary(PARTITA_CONTROLLO)
    problemi: list[str] = []
    rosters = _nodo(corpo).get("rosters")
    if not isinstance(rosters, list) or not rosters:
        return ["manca 'rosters'"]

    senza = {"team.id": 0, "roster": 0, "athlete.id": 0, "athlete.displayName": 0,
             "position.abbreviation (titolari)": 0, "stats": 0}
    mancanti_stat = {nome: 0 for nome in STATISTICHE_USATE}
    titolari = giocatori = 0
    for roster in rosters:
        if not isinstance(roster, dict):
            senza["roster"] += 1
            continue
        if not isinstance(_nodo(roster.get("team")).get("id"), (str, int)):
            senza["team.id"] += 1
        voci = roster.get("roster")
        if not isinstance(voci, list) or not voci:
            senza["roster"] += 1
            continue
        for voce in voci:
            if not isinstance(voce, dict):
                continue
            giocatori += 1
            atleta = _nodo(voce.get("athlete"))
            if atleta.get("id") in (None, ""):
                senza["athlete.id"] += 1
            if not atleta.get("displayName"):
                senza["athlete.displayName"] += 1
            if voce.get("starter"):
                titolari += 1
                if not _nodo(voce.get("position")).get("abbreviation"):
                    senza["position.abbreviation (titolari)"] += 1
            stats = voce.get("stats")
            if not isinstance(stats, list) or not stats:
                senza["stats"] += 1
                continue
            nomi = {s.get("name") for s in stats if isinstance(s, dict)}
            for nome in STATISTICHE_USATE:
                if nome not in nomi:
                    mancanti_stat[nome] += 1
    if giocatori == 0:
        problemi.append("nessun giocatore nei roster")
    if titolari == 0 and giocatori:
        problemi.append("nessun titolare ('starter') nei roster")
    for campo, n in senza.items():
        if n:
            problemi.append(f"campo '{campo}' mancante ({n} volte)")
    for nome, n in mancanti_stat.items():
        if n:
            problemi.append(f"statistica '{nome}' mancante ({n} giocatori)")

    eventi = _nodo(corpo).get("keyEvents")
    if not isinstance(eventi, list) or not eventi:
        problemi.append("manca 'keyEvents'")
    elif not any(
        isinstance(_nodo(e).get("clock"), dict)
        and isinstance(e["clock"].get("displayValue"), str)
        for e in eventi
    ):
        problemi.append("'keyEvents' senza 'clock.displayValue'")
    return problemi
