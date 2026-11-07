"""Foto dei giocatori da TheSportsDB (API v1 gratuita, chiave pubblica "123").

`searchplayers.php?p=<nome>` restituisce i giocatori con quel nome; `strCutout` è il
ritaglio PNG senza sfondo (preferito), `strThumb` la foto di ripiego. Limite gratuito:
circa 30 richieste al minuto, quindi almeno 2,2 secondi tra una richiesta e l'altra; con una
risposta 429 si smette (`LimiteFoto`). Immagini per solo uso personale.

Si accetta solo un calciatore ("Soccer") il cui nome coincide (cognome compreso, senza
badare ad accenti e maiuscole); se i candidati sono più d'uno si sceglie con la data di
nascita, poi con la squadra, altrimenti niente: meglio la maglietta che il volto sbagliato."""
from __future__ import annotations

import logging
import time
import unicodedata
from datetime import date
from urllib.parse import urlparse

import httpx

from ammonizioni.caricamento.arbitri_fd import stessa_squadra
from ammonizioni.fonti.biografie import normalizza

log = logging.getLogger(__name__)

URL_RICERCA = "https://www.thesportsdb.com/api/v1/json/123/searchplayers.php"
USER_AGENT = "ammonizioni/1.0 (uso personale)"
TIMEOUT_SECONDI = 20.0
PAUSA_SECONDI = 2.2
HOST_AMMESSI = frozenset({"r2.thesportsdb.com", "www.thesportsdb.com"})


class LimiteFoto(Exception):
    """TheSportsDB ha risposto 429: si interrompe la corsa."""


class ClientFoto(httpx.Client):
    """httpx.Client che aspetta almeno `pausa` secondi tra una richiesta e la successiva."""

    def __init__(self, *args, pausa: float = PAUSA_SECONDI, attesa=time.sleep,
                 orologio=time.monotonic, **kwargs):
        kwargs.setdefault("headers", {"User-Agent": USER_AGENT})
        kwargs.setdefault("timeout", TIMEOUT_SECONDI)
        super().__init__(*args, **kwargs)
        self._pausa = pausa
        self._attesa = attesa
        self._orologio = orologio
        self._ultima: float | None = None

    def get(self, *args, **kwargs):
        if self._ultima is not None:
            mancante = self._pausa - (self._orologio() - self._ultima)
            if mancante > 0:
                self._attesa(mancante)
        try:
            return super().get(*args, **kwargs)
        finally:
            self._ultima = self._orologio()


def crea_client() -> ClientFoto:
    return ClientFoto()


def senza_accenti(testo: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", testo) if not unicodedata.combining(c)
    )


def _stesso_nome(nome: str, candidato: str) -> bool:
    """Cognome (ultima parola) presente nel candidato e nome uguale (o iniziale)."""
    cerca = normalizza(nome).split()
    trovato = normalizza(candidato).split()
    if not cerca or not trovato or cerca[-1] not in trovato:
        return False
    if len(cerca) == 1:
        return True
    primo = cerca[0]
    return primo in trovato or (len(primo) == 1 and trovato[0].startswith(primo))


def url_valido(valore) -> str | None:
    if not isinstance(valore, str):
        return None
    try:
        parti = urlparse(valore.strip())
    except ValueError:
        return None
    if parti.scheme == "https" and parti.hostname in HOST_AMMESSI:
        return valore.strip()
    return None


def _data(valore) -> date | None:
    if isinstance(valore, str) and len(valore) >= 10:
        try:
            return date.fromisoformat(valore[:10])
        except ValueError:
            return None
    return None


def _scegli(
    candidati: list[dict], nome: str, data_nascita: date | None, squadra: str | None
) -> dict | None:
    buoni = [
        c for c in candidati
        if isinstance(c, dict)
        and c.get("strSport") == "Soccer"
        and isinstance(c.get("strPlayer"), str)
        and _stesso_nome(nome, c["strPlayer"])
    ]
    if data_nascita is not None:  # data nota e diversa: un altro giocatore
        buoni = [c for c in buoni if _data(c.get("dateBorn")) in (None, data_nascita)]
    if len(buoni) <= 1:
        return buoni[0] if buoni else None
    if data_nascita is not None:
        uguali = [c for c in buoni if _data(c.get("dateBorn")) == data_nascita]
        if len(uguali) == 1:
            return uguali[0]
        buoni = uguali or buoni
    if squadra:
        della_squadra = [
            c for c in buoni
            if isinstance(c.get("strTeam"), str) and stessa_squadra(c["strTeam"], squadra)
        ]
        if len(della_squadra) == 1:
            return della_squadra[0]
    return None


def _ricerca(client, nome: str) -> list[dict] | None:
    """Giocatori trovati con quel nome; None per errori di rete o risposta illeggibile."""
    try:
        risposta = client.get(URL_RICERCA, params={"p": nome})
    except httpx.HTTPError as errore:
        log.warning("Foto di %s non cercata: %s", nome, errore)
        return None
    if risposta.status_code == 429:
        raise LimiteFoto("TheSportsDB: troppe richieste (429)")
    if risposta.status_code != 200:
        log.warning("Foto di %s: risposta %s", nome, risposta.status_code)
        return None
    try:
        corpo = risposta.json()
    except ValueError:
        log.warning("Foto di %s: risposta non valida", nome)
        return None
    elenco = corpo.get("player") if isinstance(corpo, dict) else None
    return elenco if isinstance(elenco, list) else []


def cerca_foto(
    client, nome: str, data_nascita: date | None = None, squadra: str | None = None
) -> str | None:
    """URL della foto (ritaglio, altrimenti miniatura) del giocatore, None se non c'è o non
    è certo. Non solleva eccezioni, tranne `LimiteFoto` (429)."""
    try:
        nome = (nome or "").strip()
        if not nome:
            return None
        varianti = [nome]
        if senza_accenti(nome) != nome:
            varianti.append(senza_accenti(nome))
        for variante in varianti:
            candidati = _ricerca(client, variante)
            scelto = _scegli(candidati or [], nome, data_nascita, squadra)
            if scelto is not None:
                return url_valido(scelto.get("strCutout")) or url_valido(scelto.get("strThumb"))
        return None
    except LimiteFoto:
        raise
    except Exception as errore:  # noqa: BLE001 - mai far fallire il chiamante
        log.warning("Foto di %s non cercata: %s", nome, errore)
        return None
