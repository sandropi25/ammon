"""Fonte ESPN: API pubblica non ufficiale (nessuna chiave). Partite dal calendario
(scoreboard), statistiche e formazioni dal riepilogo della partita (summary).

ESPN non fornisce dribbling, voto, minuti ed arbitro: i dribbling valgono 0, il voto è
None, i minuti si ricavano dagli eventi (sostituzioni e cartellini rossi)."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import httpx

from ammonizioni.config import COMPETIZIONI, SLUG_ESPN
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.limite import LimiteRichieste, Priorita
from ammonizioni.fonti.tipi import FormazioneDati, PartitaDati, PresenzaDati

log = logging.getLogger(__name__)

URL_ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
USER_AGENT = "ammonizioni/1.0"
TENTATIVI = 5  # primo tentativo + 4 retry
ATTESE_RETRY = (1, 2, 4, 8)
TIMEOUT_SECONDI = 30.0
TITOLARI_PER_SQUADRA = 11
MINUTI_PARTITA = 90

# Stato ESPN -> stato interno (quello di API-Football); gli altri restano come sono.
_STATI = {
    "STATUS_FULL_TIME": "FT",
    "STATUS_FINAL_AET": "AET",
    "STATUS_FINAL_PEN": "PEN",
    "STATUS_SCHEDULED": "NS",
    "STATUS_POSTPONED": "PST",
    "STATUS_CANCELED": "CANC",
}
_STATI_SENZA_GOL = ("NS", "PST", "CANC")  # ESPN dà "0" a 0 prima del via

# Posizione ESPN (parte prima del "-") -> (ruolo, riga della griglia)
_POSIZIONI: dict[str, tuple[str, int]] = {
    "G": ("G", 1),
    "RB": ("D", 2), "LB": ("D", 2), "CD": ("D", 2), "SW": ("D", 2),
    "RWB": ("D", 2), "LWB": ("D", 2),
    "DM": ("M", 3), "CM": ("M", 3), "RM": ("M", 3), "LM": ("M", 3),
    "AM": ("M", 4),
    "F": ("F", 5), "CF": ("F", 5), "ST": ("F", 5), "RF": ("F", 5), "LF": ("F", 5),
    "RW": ("F", 5), "LW": ("F", 5),
}
# Ordine da destra a sinistra dentro la riga: destra, centro-destra, centro, centro-sinistra, sinistra
_DESTRA, _CENTRO_DESTRA, _CENTRO, _CENTRO_SINISTRA, _SINISTRA = range(5)
_BASI_A_DESTRA = ("RB", "RWB", "RM", "RF", "RW")
_BASI_A_SINISTRA = ("LB", "LWB", "LM", "LF", "LW")
_POSIZIONE_SCONOSCIUTA = ("M", 3, _CENTRO)
# Basi centrali usate con un lato davanti ("RCF", "LCB", "RDM", "LAM", ...)
_CENTRALI = {"CF": "CF", "CB": "CD", "CD": "CD", "CM": "CM", "DM": "DM", "AM": "AM"}


def _int(valore) -> int:
    try:
        return int(float(valore))
    except (TypeError, ValueError):
        return 0


def _id(valore) -> int | None:
    try:
        return int(valore)
    except (TypeError, ValueError):
        return None


def _probabilita_moneyline(valore) -> float | None:
    """Probabilità implicita (non normalizzata) di una quota americana ("+150", "-120",
    "EVEN", 150) o None se illeggibile."""
    if isinstance(valore, bool):
        return None
    if isinstance(valore, str):
        testo = valore.strip().upper()
        if testo in ("EVEN", "EV", "PK"):
            return 0.5
        try:
            valore = float(testo)
        except ValueError:
            return None
    if not isinstance(valore, (int, float)) or valore == 0 or valore != valore:
        return None
    return 100 / (valore + 100) if valore > 0 else -valore / (-valore + 100)


def _moneyline(voce, lato: str):
    """Quota americana di un lato ("home", "draw", "away") da una voce `odds` di ESPN, nei
    due formati noti: `homeTeamOdds.moneyLine` oppure `moneyline.home.close.odds`."""
    chiavi = {"home": "homeTeamOdds", "away": "awayTeamOdds", "draw": "drawOdds"}
    blocco = voce.get(chiavi[lato])
    if isinstance(blocco, dict) and blocco.get("moneyLine") is not None:
        return blocco["moneyLine"]
    nuovo = (voce.get("moneyline") or {}).get(lato)
    if isinstance(nuovo, dict):
        for momento in ("close", "open"):
            quota = (nuovo.get(momento) or {}).get("odds")
            if quota is not None:
                return quota
    return None


def probabilita_1x2(corpo: dict) -> tuple[float, float, float] | None:
    """Probabilità implicite (casa, pareggio, trasferta), normalizzate a somma 1, dalle quote
    1X2 del summary ESPN (`odds`). None se mancano o sono illeggibili."""
    odds = corpo.get("odds") if isinstance(corpo, dict) else None
    if not isinstance(odds, list):
        return None
    for voce in odds:
        if not isinstance(voce, dict):
            continue
        probabilita = [_probabilita_moneyline(_moneyline(voce, l)) for l in ("home", "draw", "away")]
        if all(p is not None for p in probabilita):
            totale = sum(probabilita)
            return tuple(p / totale for p in probabilita)
    return None


def _minuto(clock) -> int | None:
    """Minuto di gioco da un `clock` ESPN: "57'" -> 57, "45'+2'" -> 45, "90'+3'" -> 90
    (i recuperi non contano). Senza testo valido si usa il valore in secondi."""
    if not isinstance(clock, dict):
        return None
    testo = clock.get("displayValue")
    if isinstance(testo, str):
        trovato = re.match(r"\s*(\d+)", testo)
        if trovato:
            return int(trovato.group(1))
    valore = clock.get("value")
    if isinstance(valore, (int, float)) and not isinstance(valore, bool):
        return int(valore // 60)
    return None


def _classifica(abbreviazione: str) -> tuple[str, int, int] | None:
    """(ruolo, riga, posto) di una posizione ESPN, None se non riconosciuta.
    Posto 0..4 da destra a sinistra: "RB" destra, "CD-R" centro-destra, "CM" centro,
    "CD-L" centro-sinistra, "LB" sinistra."""
    base, _, lato = abbreviazione.strip().upper().partition("-")
    # varianti "lato + posizione centrale" (es. "RCF", "LCB", "RDM"): come "CF-R", "CB-L"...
    if not lato and len(base) == 3 and base[0] in "RL" and base[1:] in _CENTRALI:
        base, lato = _CENTRALI[base[1:]], base[0]
    voce = _POSIZIONI.get(base)
    if voce is None:
        return None
    if base in _BASI_A_DESTRA:
        posto = _DESTRA
    elif base in _BASI_A_SINISTRA:
        posto = _SINISTRA
    elif lato == "R":
        posto = _CENTRO_DESTRA
    elif lato == "L":
        posto = _CENTRO_SINISTRA
    else:
        posto = _CENTRO
    return voce[0], voce[1], posto


def _classifica_o_centrocampista(abbreviazione: str) -> tuple[str, int, int]:
    classe = _classifica(abbreviazione)
    if classe is None:
        log.warning(
            "Posizione ESPN sconosciuta %r: trattata come centrocampista centrale", abbreviazione
        )
        return _POSIZIONE_SCONOSCIUTA
    return classe


def _griglie(titolari: list[tuple[int, int, int, int]]) -> dict[int, str]:
    """Griglia sintetica "riga:colonna" per i titolari di una squadra, date come tuple
    (giocatore_id, riga, posto, formationPlace). Dentro la riga i giocatori vanno da destra
    a sinistra e si numerano da 1: così `avversario_diretto` trova il marcatore specchiato."""
    per_riga: dict[int, list[tuple[int, int, int]]] = {}
    for giocatore_id, riga, posto, ordine in titolari:
        per_riga.setdefault(riga, []).append((posto, ordine, giocatore_id))
    griglie = {}
    for riga, giocatori in per_riga.items():
        for colonna, (_, _, giocatore_id) in enumerate(sorted(giocatori), start=1):
            griglie[giocatore_id] = f"{riga}:{colonna}"
    return griglie


def crea_limite_espn(sessione) -> LimiteRichieste:
    """Limite per ESPN: al più 30 richieste al minuto, 5000 al giorno, nessuna riserva."""
    return LimiteRichieste(sessione, max_giorno=5000, max_minuto=30, riserva_oggi=0)


class _Giocatore:
    """Giocatore di un roster ESPN già letto (id, nome, posizione, flag)."""

    def __init__(self, voce: dict):
        atleta = voce["athlete"]
        self.id = int(atleta["id"])
        self.nome = atleta["displayName"]
        self.titolare = bool(voce.get("starter"))
        # i panchinari possono non avere la posizione (partite più vecchie); i titolari sì
        self.abbreviazione = (
            voce["position"]["abbreviation"] if self.titolare
            else ((voce.get("position") or {}).get("abbreviation") or "SUB")
        )
        self.ordine = _id(voce.get("formationPlace")) or 0
        self.voce = voce
        # (ruolo, riga, posto); i panchinari hanno posizione "SUB": nessuna classe, nessun log
        self.classe = _classifica(self.abbreviazione)
        if self.classe is None and self.titolare:
            self.classe = _classifica_o_centrocampista(self.abbreviazione)


class Espn:
    def __init__(
        self,
        limite: LimiteRichieste | None = None,
        client: httpx.Client | None = None,
        priorita: Priorita = Priorita.OGGI,
        dormi=time.sleep,
    ):
        self.limite = limite
        self.client = client if client is not None else httpx.Client(timeout=TIMEOUT_SECONDI)
        self.priorita = priorita
        self.dormi = dormi
        self._partite: dict[int, PartitaDati] = {}
        self._slug: dict[int, str] = {}
        self._quote: dict[int, tuple[float, float, float]] = {}

    # --- Fonte ---------------------------------------------------------

    def partite(self, competizione_id: int, stagione: int) -> list[PartitaDati]:
        slug = SLUG_ESPN.get(competizione_id)
        if slug is None:
            raise ErroreFonte(f"Competizione {competizione_id} sconosciuta per ESPN")
        inizio = datetime(stagione, 7, 1, tzinfo=timezone.utc)
        fine = datetime(stagione + 1, 7, 1, tzinfo=timezone.utc)
        partite: dict[int, PartitaDati] = {}
        for anno in (stagione, stagione + 1):
            corpo = self._get(f"/{slug}/scoreboard", {"dates": anno, "limit": 1000})
            eventi = corpo.get("events")
            if not isinstance(eventi, list):
                raise ErroreFonte(
                    f"Risposta ESPN senza 'events' per {slug} {anno}: struttura cambiata?"
                )
            for evento in eventi:
                try:
                    partita = self._partita(evento, competizione_id, stagione)
                except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
                    identificativo = evento.get("id") if isinstance(evento, dict) else evento
                    log.warning("Evento ESPN %s non letto (%s: %s)", identificativo,
                                type(e).__name__, e)
                    continue
                if inizio <= partita.data_utc < fine:
                    partite[partita.id] = partita
        for partita in partite.values():
            self._partite[partita.id] = partita
            self._slug[partita.id] = slug
        return list(partite.values())

    def indica_competizione(self, partita_id: int, competizione_id: int) -> None:
        """Competizione di una partita già nel database (ESPN vuole lo slug della competizione
        anche per il riepilogo): serve in un processo che non ha letto il calendario. Una
        competizione sconosciuta non cambia nulla."""
        slug = SLUG_ESPN.get(competizione_id)
        if slug is not None:
            self._slug[partita_id] = slug

    def partita(self, id: int) -> PartitaDati:
        """Solo per partite già viste con `partite()`: ESPN non permette di leggerne una
        per solo id senza conoscere il campionato."""
        if id not in self._partite:
            raise ErroreFonte(f"Partita {id} non trovata (ESPN: prima si legge il calendario)")
        return self._partite[id]

    def statistiche(self, partita_id: int) -> list[PresenzaDati]:
        corpo = self._summary(partita_id)
        entrate, uscite = self._minuti_eventi(corpo.get("keyEvents"))
        presenze: list[PresenzaDati] = []
        for squadra in self._rosters(corpo, partita_id):
            squadra_id = _id((squadra.get("team") or {}).get("id"))
            giocatori = self._giocatori(squadra, partita_id)
            if squadra_id is None or giocatori is None:
                continue
            griglie = self._griglie_titolari(giocatori)
            for g in giocatori:
                presenza = self._presenza(partita_id, squadra_id, g, griglie, entrate, uscite)
                if presenza is not None:
                    presenze.append(presenza)
        return presenze

    def quote_1x2(self, partita_id: int) -> tuple[float, float, float] | None:
        """Probabilità implicite (casa, pareggio, trasferta) lette dall'ultima chiamata a
        `formazioni` per la partita (stesso summary, nessuna richiesta in più)."""
        return self._quote.get(partita_id)

    def formazioni(self, partita_id: int) -> list[FormazioneDati]:
        corpo = self._summary(partita_id)
        quote = probabilita_1x2(corpo)
        if quote is not None:
            self._quote[partita_id] = quote
        formazioni = []
        for squadra in self._rosters(corpo, partita_id):
            squadra_id = _id((squadra.get("team") or {}).get("id"))
            giocatori = self._giocatori(squadra, partita_id)
            if squadra_id is None or giocatori is None:
                continue
            titolari = [g for g in giocatori if g.titolare]
            if len(titolari) != TITOLARI_PER_SQUADRA:
                continue  # formazione non ancora uscita
            griglie = self._griglie_titolari(giocatori)
            elenco = []
            for g in sorted(titolari, key=lambda g: (g.classe[1], g.ordine, g.id)):
                elenco.append((g.id, g.nome, g.classe[0], griglie[g.id]))
            # il resto del roster è la panchina (posizione "SUB": ruolo da altre partite)
            panchina = [
                (g.id, g.nome, g.classe[0] if g.classe else None)
                for g in sorted(giocatori, key=lambda g: g.id) if not g.titolare
            ]
            formazioni.append(
                FormazioneDati(
                    partita_id=partita_id, squadra_id=squadra_id, titolari=elenco,
                    panchina=panchina,
                )
            )
        return formazioni

    # --- conversioni ---------------------------------------------------

    @staticmethod
    def _partita(evento: dict, competizione_id: int, stagione: int) -> PartitaDati:
        data = datetime.fromisoformat(evento["date"])
        if data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)
        competizione = evento["competitions"][0]
        squadre = {c["homeAway"]: c for c in competizione["competitors"]}
        casa, trasferta = squadre["home"], squadre["away"]
        stato_espn = (evento.get("status") or competizione["status"])["type"]["name"]
        stato = _STATI.get(stato_espn, stato_espn)
        senza_gol = stato in _STATI_SENZA_GOL
        return PartitaDati(
            id=int(evento["id"]),
            data_utc=data.astimezone(timezone.utc),
            competizione_id=competizione_id,
            stagione=stagione,
            giornata=_giornata(evento, competizione),
            casa_id=int(casa["team"]["id"]),
            casa_nome=casa["team"]["displayName"],
            trasferta_id=int(trasferta["team"]["id"]),
            trasferta_nome=trasferta["team"]["displayName"],
            arbitro_nome=None,  # arriva da football-data.org
            gol_casa=None if senza_gol else int(casa["score"]),
            gol_trasferta=None if senza_gol else int(trasferta["score"]),
            stato=stato,
        )

    def summary(self, partita_id: int) -> dict:
        """Risposta grezza di ESPN per una partita (usata dal controllo di salute)."""
        return self._summary(partita_id)

    def _summary(self, partita_id: int) -> dict:
        slug = self._slug.get(partita_id, SLUG_ESPN[COMPETIZIONI["serie_a"]])
        return self._get(f"/{slug}/summary", {"event": partita_id})

    @staticmethod
    def _rosters(corpo: dict, partita_id: int) -> list[dict]:
        rosters = corpo.get("rosters")
        if not isinstance(rosters, list) or not rosters:
            raise ErroreFonte(
                f"Partita {partita_id}: risposta ESPN senza 'rosters' (struttura cambiata?)"
            )
        return [r for r in rosters if isinstance(r, dict)]

    @staticmethod
    def _giocatori(squadra: dict, partita_id: int) -> list[_Giocatore] | None:
        """Giocatori leggibili del roster di una squadra; None se la squadra non ha
        ancora il roster (partita da giocare). Chi non ha id, nome o posizione è saltato."""
        roster = squadra.get("roster")
        if not isinstance(roster, list):
            return None
        giocatori = []
        for voce in roster:
            try:
                giocatori.append(_Giocatore(voce))
            except (KeyError, TypeError, ValueError, AttributeError):
                log.warning(
                    "Partita %s: giocatore ESPN senza id, nome o posizione, saltato", partita_id
                )
        return giocatori

    @staticmethod
    def _griglie_titolari(giocatori: list[_Giocatore]) -> dict[int, str]:
        """Griglia dei titolari; vuota se non sono 11 (mai griglie parziali)."""
        titolari = [
            (g.id, g.classe[1], g.classe[2], g.ordine) for g in giocatori if g.titolare
        ]
        if len(titolari) != TITOLARI_PER_SQUADRA:
            return {}
        return _griglie(titolari)

    @staticmethod
    def _minuti_eventi(eventi) -> tuple[dict[int, int], dict[int, int]]:
        """Minuto di entrata e di uscita per giocatore, da `keyEvents`: in una sostituzione
        il primo partecipante entra e il secondo esce; un rosso (anche il secondo giallo)
        fa uscire il giocatore."""
        entrate: dict[int, int] = {}
        uscite: dict[int, int] = {}
        if not isinstance(eventi, list):
            return entrate, uscite
        for evento in eventi:
            if not isinstance(evento, dict):
                continue
            tipo = evento.get("type") or {}
            codice = str(tipo.get("type") or "").lower()
            testo = str(tipo.get("text") or "").lower()
            minuto = _minuto(evento.get("clock"))
            partecipanti = [
                _id(((p or {}).get("athlete") or {}).get("id"))
                for p in evento.get("participants") or []
            ]
            if minuto is None or not partecipanti:
                continue
            if codice == "substitution" or testo == "substitution":
                if len(partecipanti) >= 2:
                    if partecipanti[0] is not None:
                        entrate[partecipanti[0]] = minuto
                    if partecipanti[1] is not None:
                        uscite[partecipanti[1]] = min(minuto, uscite.get(partecipanti[1], minuto))
            elif codice.startswith("red") or "red-card" in codice or "red card" in testo:
                if partecipanti[0] is not None:
                    uscite[partecipanti[0]] = min(minuto, uscite.get(partecipanti[0], minuto))
        return entrate, uscite

    def _presenza(
        self,
        partita_id: int,
        squadra_id: int,
        g: _Giocatore,
        griglie: dict[int, str],
        entrate: dict[int, int],
        uscite: dict[int, int],
    ) -> PresenzaDati | None:
        stats = g.voce.get("stats")
        if not isinstance(stats, list) or not stats:
            log.warning("Partita %s: %s senza statistiche, saltato", partita_id, g.nome)
            return None
        valori = {s.get("name"): s.get("value") for s in stats if isinstance(s, dict)}
        # i panchinari hanno posizione "SUB": il ruolo si conosce solo da altre partite
        ruolo = g.classe[0] if g.classe else None
        griglia = griglie.get(g.id)  # solo i titolari
        return PresenzaDati(
            partita_id=partita_id,
            giocatore_id=g.id,
            giocatore_nome=g.nome,
            squadra_id=squadra_id,
            titolare=g.titolare,
            ruolo=ruolo,
            griglia=griglia,
            minuti=self._minuti(partita_id, g, entrate, uscite),
            gialli=_int(valori.get("yellowCards")),
            rossi=_int(valori.get("redCards")),
            falli_commessi=_int(valori.get("foulsCommitted")),
            falli_subiti=_int(valori.get("foulsSuffered")),
            dribbling_tentati=0,  # ESPN non li fornisce
            dribbling_riusciti=0,
            tiri=_int(valori.get("totalShots")),
            gol=_int(valori.get("totalGoals")),
            assist=_int(valori.get("goalAssists")),
            voto=None,  # ESPN non lo fornisce
        )

    @staticmethod
    def _minuti(
        partita_id: int, g: _Giocatore, entrate: dict[int, int], uscite: dict[int, int]
    ) -> int:
        if g.titolare:
            entrata = 0
        else:
            entrata = entrate.get(g.id)
            if entrata is None and g.voce.get("subbedIn"):
                for azione in g.voce.get("plays") or []:
                    if isinstance(azione, dict) and azione.get("substitution"):
                        entrata = _minuto(azione.get("clock"))
                        break
            if entrata is None:
                if g.voce.get("subbedIn"):
                    log.warning(
                        "Partita %s: %s è entrato ma manca il minuto della sostituzione",
                        partita_id, g.nome,
                    )
                return 0  # non è entrato
        uscita = uscite.get(g.id)
        if uscita is None:
            if g.voce.get("subbedOut"):
                log.warning(
                    "Partita %s: %s è uscito ma manca il minuto: contati 90",
                    partita_id, g.nome,
                )
            uscita = MINUTI_PARTITA
        # recuperi e supplementari contano come 90
        entrata, uscita = min(entrata, MINUTI_PARTITA), min(uscita, MINUTI_PARTITA)
        minuti = max(0, uscita - entrata)
        # un subentrato entrato nei recuperi (o nei supplementari) ha giocato: almeno 1 minuto
        return max(1, minuti) if not g.titolare else minuti

    # --- HTTP con limite e retry ---------------------------------------

    def _get(self, percorso: str, parametri: dict) -> dict:
        ultimo_errore = "errore sconosciuto"
        for tentativo in range(TENTATIVI):
            if tentativo > 0:
                self.dormi(ATTESE_RETRY[tentativo - 1])
            # prima della chiamata: se il budget è finito non si fa nessuna richiesta
            if self.limite is not None:
                self.limite.prendi(self.priorita)
            try:
                risposta = self.client.get(
                    URL_ESPN + percorso,
                    params=parametri,
                    headers={"User-Agent": USER_AGENT},
                )
            except httpx.TransportError as e:
                ultimo_errore = f"errore di rete: {e}"
                continue
            if risposta.status_code == 429 or risposta.status_code >= 500:
                ultimo_errore = f"HTTP {risposta.status_code}"
                continue
            if risposta.status_code != 200:
                raise ErroreFonte(f"HTTP {risposta.status_code} su {percorso}")
            try:
                corpo = risposta.json()
            except ValueError as e:
                raise ErroreFonte(f"Risposta non valida su {percorso}: {e}") from e
            if not isinstance(corpo, dict):
                raise ErroreFonte(f"Risposta non valida su {percorso}: non è un oggetto JSON")
            return corpo
        raise ErroreFonte(f"{percorso}: {TENTATIVI} tentativi falliti ({ultimo_errore})")


def _giornata(evento: dict, competizione: dict) -> int | None:
    """Giornata dalla settimana del campionato, se ESPN la dà (di solito no)."""
    for sorgente in (evento, competizione):
        settimana = sorgente.get("week")
        numero = settimana.get("number") if isinstance(settimana, dict) else settimana
        if isinstance(numero, int) and not isinstance(numero, bool):
            return numero
    return None
