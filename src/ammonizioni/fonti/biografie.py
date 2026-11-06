"""Biografie dei giocatori: anagrafica da ESPN e breve profilo da Wikipedia.

- ESPN (API pubblica non ufficiale, nessuna chiave): una richiesta per giocatore a
  `site.web.api.espn.com/apis/common/v3/sports/soccer/athletes/<id>` (gli id dei giocatori
  del database sono quelli ESPN quando la fonte dati è ESPN). Dà data di nascita,
  cittadinanza, altezza (in piedi e pollici) e ruolo.
- Wikipedia: il titolo si trova con l'API di ricerca ("<nome> calciatore" su it, poi
  "<nome> footballer" su en), il testo con l'API REST di riepilogo. Il testo è CC BY-SA:
  chi lo mostra deve citare "Fonte: Wikipedia" con il link alla voce.

Se la voce trovata non è chiaramente quella di un calciatore con quel nome (pagina di
disambiguazione, persona diversa, anno di nascita diverso) non si restituisce nulla."""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote

import httpx

from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.limite import LimiteRichieste, Priorita

log = logging.getLogger(__name__)

URL_ATLETA_ESPN = "https://site.web.api.espn.com/apis/common/v3/sports/soccer/athletes/{id}"
URL_WIKI_API = "https://{lingua}.wikipedia.org/w/api.php"
URL_WIKI_RIASSUNTO = "https://{lingua}.wikipedia.org/api/rest_v1/page/summary/{titolo}"
USER_AGENT = "Cartellino/1.0 (https://github.com/sandropi25/ammon; biografie calciatori)"
TIMEOUT_SECONDI = 20.0
TENTATIVI = 2
ATTESA_RETRY = 2.0
CANDIDATI_WIKI = 3  # titoli della ricerca controllati per lingua
LUNGHEZZA_ESTRATTO = 600
CM_PER_POLLICE = 2.54

# lingua -> (parola aggiunta alla ricerca, radici che dicono "calciatore")
LINGUE_WIKI: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("it", "calciatore", ("calciator", "calciatric")),
    ("en", "footballer", ("footballer", "football player", "soccer player", "association football")),
)

POSIZIONI = {
    "goalkeeper": "Portiere",
    "defender": "Difensore",
    "midfielder": "Centrocampista",
    "forward": "Attaccante",
}
# cittadinanze ESPN (in inglese) più frequenti in Serie A e Liga; le altre restano in inglese
NAZIONI = {
    "Italy": "Italia", "Spain": "Spagna", "France": "Francia", "Germany": "Germania",
    "Portugal": "Portogallo", "Brazil": "Brasile", "Argentina": "Argentina",
    "Netherlands": "Paesi Bassi", "Belgium": "Belgio", "England": "Inghilterra",
    "Scotland": "Scozia", "Wales": "Galles", "Ireland": "Irlanda",
    "Northern Ireland": "Irlanda del Nord", "Switzerland": "Svizzera", "Austria": "Austria",
    "Croatia": "Croazia", "Serbia": "Serbia", "Slovenia": "Slovenia", "Slovakia": "Slovacchia",
    "Poland": "Polonia", "Czechia": "Cechia", "Czech Republic": "Repubblica Ceca",
    "Denmark": "Danimarca", "Sweden": "Svezia", "Norway": "Norvegia", "Finland": "Finlandia",
    "Iceland": "Islanda", "Greece": "Grecia", "Turkey": "Turchia", "Türkiye": "Turchia",
    "Albania": "Albania", "Kosovo": "Kosovo", "North Macedonia": "Macedonia del Nord",
    "Montenegro": "Montenegro", "Bosnia and Herzegovina": "Bosnia ed Erzegovina",
    "Romania": "Romania", "Hungary": "Ungheria", "Bulgaria": "Bulgaria", "Ukraine": "Ucraina",
    "Georgia": "Georgia", "Russia": "Russia", "Uruguay": "Uruguay", "Colombia": "Colombia",
    "Chile": "Cile", "Paraguay": "Paraguay", "Peru": "Perù", "Ecuador": "Ecuador",
    "Venezuela": "Venezuela", "Mexico": "Messico", "United States": "Stati Uniti",
    "USA": "Stati Uniti", "Canada": "Canada", "Morocco": "Marocco", "Algeria": "Algeria",
    "Tunisia": "Tunisia", "Senegal": "Senegal", "Nigeria": "Nigeria", "Ghana": "Ghana",
    "Ivory Coast": "Costa d'Avorio", "Côte d'Ivoire": "Costa d'Avorio", "Cameroon": "Camerun",
    "Mali": "Mali", "Guinea": "Guinea", "Gambia": "Gambia", "Gabon": "Gabon",
    "Egypt": "Egitto", "Japan": "Giappone", "South Korea": "Corea del Sud",
    "Korea Republic": "Corea del Sud", "Australia": "Australia",
}


@dataclass(frozen=True)
class Anagrafica:
    data_nascita: date | None
    nazionalita: str | None
    altezza_cm: int | None
    posizione: str | None


@dataclass(frozen=True)
class ProfiloWiki:
    titolo: str
    url: str
    estratto: str
    lingua: str


# ---------------------------------------------------------------- ESPN: lettura

def _data_nascita(atleta: dict) -> date | None:
    iso = atleta.get("dateOfBirth")
    if isinstance(iso, str) and len(iso) >= 10:
        try:
            return date.fromisoformat(iso[:10])
        except ValueError:
            pass
    testo = atleta.get("displayDOB")
    if isinstance(testo, str):
        try:
            return datetime.strptime(testo.strip(), "%d/%m/%Y").date()
        except ValueError:
            return None
    return None


def altezza_cm(atleta: dict) -> int | None:
    """Altezza in centimetri da `height` (pollici) o da `displayHeight` ("6' 4\"",
    "1.93 m", "193 cm"); None se manca o non è plausibile."""
    pollici = atleta.get("height")
    cm: float | None = None
    if isinstance(pollici, (int, float)) and not isinstance(pollici, bool) and pollici > 0:
        cm = pollici * CM_PER_POLLICE
    else:
        testo = str(atleta.get("displayHeight") or "")
        piedi = re.match(r"\s*(\d+)\s*'\s*(\d+)?", testo)
        metri = re.match(r"\s*(\d)[.,](\d{2})\s*m\b", testo)
        centimetri = re.match(r"\s*(\d{3})\s*cm\b", testo)
        if piedi:
            cm = (int(piedi.group(1)) * 12 + int(piedi.group(2) or 0)) * CM_PER_POLLICE
        elif metri:
            cm = int(metri.group(1)) * 100 + int(metri.group(2))
        elif centimetri:
            cm = int(centimetri.group(1))
    if cm is None or not 140 <= cm <= 220:
        return None
    return round(cm)


def leggi_anagrafica(corpo: dict) -> Anagrafica | None:
    """Anagrafica dalla risposta dell'endpoint atleta (None se non c'è l'atleta)."""
    atleta = corpo.get("athlete") if isinstance(corpo, dict) else None
    if not isinstance(atleta, dict):
        return None
    nazione = atleta.get("citizenship")
    nazione = NAZIONI.get(nazione, nazione) if isinstance(nazione, str) and nazione else None
    posizione = (atleta.get("position") or {}).get("name") or (atleta.get("position") or {}).get(
        "displayName"
    )
    posizione = (
        POSIZIONI.get(posizione.strip().lower(), posizione.strip())
        if isinstance(posizione, str) and posizione.strip() else None
    )
    return Anagrafica(
        data_nascita=_data_nascita(atleta),
        nazionalita=nazione,
        altezza_cm=altezza_cm(atleta),
        posizione=posizione,
    )


# ---------------------------------------------------------------- Wikipedia: controlli

def normalizza(testo: str) -> str:
    """Minuscole, senza accenti né punteggiatura: "Álex Baena" -> "alex baena"."""
    senza = "".join(
        c for c in unicodedata.normalize("NFKD", testo) if not unicodedata.combining(c)
    )
    return " ".join(re.findall(r"[a-z0-9]+", senza.lower()))


def stesso_nome(nome: str, titolo: str) -> bool:
    """Il titolo della voce contiene il cognome (ultima parola) e, se c'è, il nome."""
    parole_nome = normalizza(nome).split()
    parole_titolo = set(normalizza(re.sub(r"\(.*?\)", " ", titolo)).split())
    if not parole_nome:
        return False
    if parole_nome[-1] not in parole_titolo:
        return False
    return len(parole_nome) == 1 or parole_nome[0] in parole_titolo


def _anni(testo: str) -> list[int]:
    return [int(a) for a in re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", testo)]


def e_calciatore(
    riassunto: dict, nome: str, lingua: str, anno_nascita: int | None = None
) -> bool:
    """La voce è quella del calciatore cercato? Voce normale (non disambiguazione), titolo
    con lo stesso nome, descrizione o inizio del testo che dicono "calciatore"; se si
    conosce l'anno di nascita e la descrizione ne indica uno, devono coincidere."""
    if not isinstance(riassunto, dict) or riassunto.get("type") != "standard":
        return False
    titolo = str(riassunto.get("title") or "")
    if not stesso_nome(nome, titolo):
        return False
    radici = next(r for lng, _, r in LINGUE_WIKI if lng == lingua)
    descrizione = str(riassunto.get("description") or "").lower()
    inizio = str(riassunto.get("extract") or "")[:300].lower()
    if not any(r in descrizione or r in inizio for r in radici):
        return False
    if anno_nascita is not None:
        anni = _anni(descrizione) or _anni(inizio[:160])
        if anni and anno_nascita not in anni:
            return False
    return True


def taglia_estratto(testo: str, massimo: int = LUNGHEZZA_ESTRATTO) -> str:
    """Al più `massimo` caratteri, tagliando a fine frase (o a fine parola con "…")."""
    testo = " ".join(testo.split())
    if len(testo) <= massimo:
        return testo
    pezzo = testo[:massimo]
    fine = pezzo.rfind(". ")
    if fine >= massimo // 2:
        return pezzo[: fine + 1]
    return pezzo[: pezzo.rfind(" ")].rstrip(",;:") + "…"


# ---------------------------------------------------------------- client HTTP

class ClientBiografie:
    """Le richieste a ESPN passano dal limite (se dato), quelle a Wikipedia no (poche per
    notte, una dopo l'altra, con uno User-Agent che identifica l'app come chiede Wikimedia)."""

    def __init__(
        self,
        limite: LimiteRichieste | None = None,
        client: httpx.Client | None = None,
        dormi=time.sleep,
    ):
        self.limite = limite
        self.client = client if client is not None else httpx.Client(timeout=TIMEOUT_SECONDI)
        self.dormi = dormi
        self.richieste = 0

    def _get(self, url: str, parametri: dict | None = None, espn: bool = False) -> dict | None:
        """JSON della risposta; None se la pagina non esiste (404). ErroreFonte dopo i
        tentativi falliti. Solleva LimiteSuperato se il budget ESPN è finito."""
        errore = "errore sconosciuto"
        for tentativo in range(TENTATIVI):
            if tentativo:
                self.dormi(ATTESA_RETRY)
            if espn and self.limite is not None:
                self.limite.prendi(Priorita.STORICO)
            self.richieste += 1
            try:
                risposta = self.client.get(
                    url, params=parametri, headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                )
            except httpx.TransportError as e:
                errore = f"errore di rete: {e}"
                continue
            if risposta.status_code == 404:
                return None
            if risposta.status_code == 429 or risposta.status_code >= 500:
                errore = f"HTTP {risposta.status_code}"
                continue
            if risposta.status_code != 200:
                raise ErroreFonte(f"HTTP {risposta.status_code} su {url}")
            try:
                corpo = risposta.json()
            except ValueError as e:
                raise ErroreFonte(f"Risposta non valida su {url}: {e}") from e
            return corpo if isinstance(corpo, dict) else None
        raise ErroreFonte(f"{url}: {TENTATIVI} tentativi falliti ({errore})")

    def anagrafica(self, espn_id: int) -> Anagrafica | None:
        corpo = self._get(URL_ATLETA_ESPN.format(id=int(espn_id)), espn=True)
        return leggi_anagrafica(corpo) if corpo else None

    def _titoli(self, lingua: str, ricerca: str) -> list[str]:
        corpo = self._get(
            URL_WIKI_API.format(lingua=lingua),
            {
                "action": "query", "list": "search", "srsearch": ricerca, "format": "json",
                "srlimit": CANDIDATI_WIKI, "srprop": "", "srnamespace": 0,
            },
        )
        voci = ((corpo or {}).get("query") or {}).get("search") or []
        return [str(v["title"]) for v in voci if isinstance(v, dict) and v.get("title")]

    def _riassunto(self, lingua: str, titolo: str) -> dict | None:
        return self._get(
            URL_WIKI_RIASSUNTO.format(
                lingua=lingua, titolo=quote(titolo.replace(" ", "_"), safe="")
            )
        )

    def profilo_wikipedia(self, nome: str, anno_nascita: int | None = None) -> ProfiloWiki | None:
        """Profilo della voce del calciatore (it, altrimenti en); None se non c'è una voce
        sicuramente sua."""
        for lingua, parola, _ in LINGUE_WIKI:
            for titolo in self._titoli(lingua, f"{nome} {parola}"):
                if not stesso_nome(nome, titolo):
                    continue
                riassunto = self._riassunto(lingua, titolo)
                if riassunto is None or not e_calciatore(riassunto, nome, lingua, anno_nascita):
                    continue
                estratto = taglia_estratto(str(riassunto.get("extract") or ""))
                url = (
                    ((riassunto.get("content_urls") or {}).get("desktop") or {}).get("page")
                    or f"https://{lingua}.wikipedia.org/wiki/{quote(titolo.replace(' ', '_'))}"
                )
                if not estratto or not str(url).startswith(f"https://{lingua}.wikipedia.org/"):
                    continue
                return ProfiloWiki(
                    titolo=str(riassunto.get("title") or titolo), url=str(url),
                    estratto=estratto, lingua=lingua,
                )
        return None
