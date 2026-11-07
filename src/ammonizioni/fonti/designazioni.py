"""Designazioni ufficiali degli arbitri di Serie A, dal sito dell'AIA (aia-figc.it).

L'AIA pubblica le designazioni 2-4 giorni prima, come articoli HTML semplici ("SERIE A
ENILIVE - DESIGNAZIONI 11a GIORNATA", e le eventuali "VARIAZIONE DESIGNAZIONI"). Un blocco per
partita: titolo "TORINO - LECCE" con giorno e ora, poi l'arbitro, gli assistenti e "IV:",
"VAR:", "AVAR:". Il robots.txt del sito vieta solo /private.

La Liga non e' coperta: la RFEF (rfef.es, robots.txt permissivo) pubblica le designazioni
solo come PDF allegato e immagine, mai come testo nella pagina.

Se la struttura cambia, i parser restituiscono [] e scrivono un avviso nel log: non
sollevano mai eccezioni."""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "ammonizioni/1.0 (uso personale)"
URL_INDICE_AIA = "https://www.aia-figc.it/designazioni/can/"
URL_HOME_AIA = "https://www.aia-figc.it/"
ARTICOLI_MAX = 3  # i piu' recenti: la giornata e le sue variazioni
TIMEOUT_SECONDI = 20.0


@dataclass(frozen=True)
class Designazione:
    casa: str  # come scritto dall'AIA ("INTER", "HELLAS VERONA")
    trasferta: str
    data_ora_locale: datetime | None  # ora italiana, senza fuso; None se non leggibile
    arbitro: str  # come scritto dall'AIA ("SACCHI J.L.")
    var: str | None = None


def crea_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDI, follow_redirects=True
    )


def _testo(frammento: str) -> str:
    """Testo di un frammento HTML: senza tag, entita' decodificate, spazi compattati."""
    senza_tag = re.sub(r"<[^>]*>", " ", frammento)
    return re.sub(r"\s+", " ", html.unescape(senza_tag).replace("\xa0", " ")).strip()


def _scarica(client, url: str) -> str | None:
    try:
        risposta = client.get(url)
        risposta.raise_for_status()
        return risposta.text
    except httpx.HTTPError as errore:
        log.warning("Designazioni AIA: pagina %s non letta (%s)", url, errore)
        return None


def _articoli_serie_a(testo_html: str, base: str) -> list[str]:
    """Indirizzi degli articoli di designazioni di Serie A, nell'ordine della pagina (dal
    piu' recente), senza doppioni."""
    trovati: list[str] = []
    for href, titolo in re.findall(
        r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', testo_html, flags=re.S | re.I
    ):
        t = _testo(titolo).lower()
        if "serie a" not in t or "designazioni" not in t:
            continue
        if any(parola in t for parola in ("femminil", "futsal", "calcio a 5")):
            continue
        url = urljoin(base, html.unescape(href))
        if url not in trovati:
            trovati.append(url)
    return trovati


_GIORNI = "lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica"
_INTESTAZIONE = re.compile(
    r"^(?P<casa>[^–\-]+?)\s+[–-]\s+(?P<trasferta>[^–\-]+?)\s+"
    rf"(?:{_GIORNI})\s+(?P<g>\d{{1,2}})/(?P<m>\d{{1,2}})"
    r"(?:\D+?(?P<h>\d{1,2})[.:](?P<min>\d{2}))?\s*$",
    re.I,
)
_NOME = re.compile(r"^[A-Za-zÀ-ÿ'’. ]{3,40}$")


def _data_ora(giorno: int, mese: int, ora: str | None, minuti: str | None, oggi: date) -> datetime | None:
    if ora is None or minuti is None:
        return None
    anno = oggi.year
    try:
        quando = datetime(anno, mese, giorno, int(ora), int(minuti))
        # l'AIA non scrive l'anno: l'anno e' quello per cui la data non e' molto passata
        if (oggi - quando.date()).days > 180:
            quando = quando.replace(year=anno + 1)
        elif (quando.date() - oggi).days > 185:
            quando = quando.replace(year=anno - 1)
        return quando
    except ValueError:
        return None


def parsa_articolo_aia(testo_html: str, oggi: date | None = None) -> list[Designazione]:
    """Le designazioni di un articolo AIA; [] se non riconosce nessun blocco."""
    oggi = oggi or date.today()
    paragrafi = [
        t
        for t in (_testo(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", testo_html, flags=re.S | re.I))
        if t
    ]
    risultato: list[Designazione] = []
    i = 0
    while i < len(paragrafi):
        m = _INTESTAZIONE.match(paragrafi[i])
        if m is None:
            i += 1
            continue
        i += 1
        arbitro = None
        if i < len(paragrafi):
            candidato = re.sub(r"\(.*?\)", "", paragrafi[i]).strip()
            if (
                _NOME.match(candidato)
                and not re.match(r"(IV|VAR|AVAR)\b", candidato, re.I)
                and not _INTESTAZIONE.match(paragrafi[i])
            ):
                arbitro = candidato
                i += 1
        var = None
        j = i
        while j < len(paragrafi) and _INTESTAZIONE.match(paragrafi[j]) is None:
            v = re.match(r"VAR\s*:\s*(.+)$", paragrafi[j], re.I)
            if v:
                var = v.group(1).strip() or None
            j += 1
        i = j
        if arbitro is None:
            log.warning("Designazioni AIA: arbitro non leggibile per %s - %s",
                        m.group("casa").strip(), m.group("trasferta").strip())
            continue
        risultato.append(
            Designazione(
                casa=m.group("casa").strip(),
                trasferta=m.group("trasferta").strip(),
                data_ora_locale=_data_ora(
                    int(m.group("g")), int(m.group("m")), m.group("h"), m.group("min"), oggi
                ),
                arbitro=arbitro,
                var=var,
            )
        )
    return risultato


def designazioni_serie_a(client, oggi: date | None = None) -> list[Designazione]:
    """Designazioni degli ultimi articoli AIA di Serie A (le piu' recenti per prime, cosi'
    una variazione vince sulla designazione originale). [] con avviso se qualcosa non torna."""
    try:
        elenco: list[str] = []
        for pagina in (URL_INDICE_AIA, URL_HOME_AIA):
            testo = _scarica(client, pagina)
            if testo is not None:
                elenco = _articoli_serie_a(testo, pagina)
            if elenco:
                break
        if not elenco:
            log.warning(
                "Designazioni AIA: nessun articolo di designazioni di Serie A trovato "
                "(sito cambiato o non raggiungibile?)"
            )
            return []
        risultato: list[Designazione] = []
        viste: set[tuple[str, str]] = set()
        for url in elenco[:ARTICOLI_MAX]:
            testo = _scarica(client, url)
            if testo is None:
                continue
            designazioni = parsa_articolo_aia(testo, oggi)
            if not designazioni:
                log.warning(
                    "Designazioni AIA: nessuna partita riconosciuta in %s "
                    "(struttura cambiata?)", url,
                )
            for d in designazioni:
                chiave = (d.casa.lower(), d.trasferta.lower())
                if chiave not in viste:
                    viste.add(chiave)
                    risultato.append(d)
        return risultato
    except Exception:  # noqa: BLE001 - le designazioni non devono mai fermare un job
        log.warning("Designazioni AIA: lettura non riuscita, struttura inattesa", exc_info=True)
        return []
