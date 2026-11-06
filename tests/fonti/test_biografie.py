"""Biografie: lettura dell'anagrafica ESPN e ricerca della voce Wikipedia (senza rete)."""
from datetime import date

import httpx
import pytest
import respx

from ammonizioni.fonti import biografie as bio
from ammonizioni.fonti.base import ErroreFonte
from ammonizioni.fonti.espn import crea_limite_espn
from ammonizioni.fonti.limite import LimiteSuperato, Priorita

# risposta reale (ridotta) dell'endpoint atleta, letta il 6 novembre 2026
ATLETA = {
    "athlete": {
        "id": "181836", "displayName": "Ivan Provedel",
        "position": {"id": "1", "name": "Goalkeeper", "displayName": "Goalkeeper", "abbreviation": "G"},
        "displayHeight": "6' 4\"", "displayWeight": "181 lbs", "displayDOB": "17/3/1994",
        "age": 32, "citizenship": "Italy",
    }
}
URL_ATLETA = bio.URL_ATLETA_ESPN.format(id=181836)
WIKI_IT = bio.URL_WIKI_API.format(lingua="it")
WIKI_EN = bio.URL_WIKI_API.format(lingua="en")


def riassunto(titolo, descrizione, estratto, tipo="standard", lingua="it"):
    return {
        "type": tipo, "title": titolo, "description": descrizione, "extract": estratto,
        "content_urls": {"desktop": {"page": f"https://{lingua}.wikipedia.org/wiki/{titolo.replace(' ', '_')}"}},
    }


def ricerca(*titoli):
    return {"query": {"search": [{"ns": 0, "title": t} for t in titoli]}}


@pytest.fixture
def client():
    with httpx.Client() as http:
        yield bio.ClientBiografie(client=http, dormi=lambda s: None)


# ---------------------------------------------------------------- ESPN

def test_anagrafica_dalla_risposta_espn():
    a = bio.leggi_anagrafica(ATLETA)
    assert a == bio.Anagrafica(
        data_nascita=date(1994, 3, 17), nazionalita="Italia", altezza_cm=193, posizione="Portiere"
    )


def test_altezza_in_vari_formati():
    assert bio.altezza_cm({"height": 76.0}) == 193
    assert bio.altezza_cm({"displayHeight": "5' 11\""}) == 180
    assert bio.altezza_cm({"displayHeight": "1.85 m"}) == 185
    assert bio.altezza_cm({"displayHeight": "185 cm"}) == 185
    assert bio.altezza_cm({"displayHeight": "--"}) is None
    assert bio.altezza_cm({"height": 3}) is None  # non plausibile


def test_anagrafica_parziale_e_vuota():
    a = bio.leggi_anagrafica({"athlete": {"dateOfBirth": "2001-07-02T07:00Z", "citizenship": "Kenya"}})
    assert a.data_nascita == date(2001, 7, 2) and a.nazionalita == "Kenya"
    assert a.altezza_cm is None and a.posizione is None
    assert bio.leggi_anagrafica({}) is None
    assert bio.leggi_anagrafica({"athlete": "x"}) is None


@respx.mock
def test_anagrafica_con_limite_e_404(sessione, client):
    client.limite = crea_limite_espn(sessione)
    respx.get(URL_ATLETA).mock(return_value=httpx.Response(200, json=ATLETA))
    respx.get(bio.URL_ATLETA_ESPN.format(id=5)).mock(return_value=httpx.Response(404, json={"code": 404}))
    assert client.anagrafica(181836).posizione == "Portiere"
    assert client.anagrafica(5) is None
    assert client.limite.rimanenti(Priorita.STORICO) == 5000 - 2  # contate nel limite ESPN


@respx.mock
def test_anagrafica_errori(sessione, client):
    respx.get(URL_ATLETA).mock(return_value=httpx.Response(503))
    with pytest.raises(ErroreFonte):
        client.anagrafica(181836)
    limite = crea_limite_espn(sessione)
    limite.max_giorno = 0
    client.limite = limite
    with pytest.raises(LimiteSuperato):
        client.anagrafica(181836)


# ---------------------------------------------------------------- Wikipedia: controlli

def test_normalizza_e_stesso_nome():
    assert bio.normalizza("Álex Baena") == "alex baena"
    assert bio.stesso_nome("Alex Baena", "Álex Baena")
    assert bio.stesso_nome("Josep Martínez", "Josep Martínez (calciatore 1998)")
    assert bio.stesso_nome("Pedri", "Pedri")
    assert not bio.stesso_nome("Ivan Provedel", "Christos Mandas")
    assert not bio.stesso_nome("Marco Rossi", "Paolo Rossi")


def test_e_calciatore():
    voce = riassunto("Ivan Provedel", "calciatore italiano (1994-)", "Ivan Provedel è un calciatore italiano.")
    assert bio.e_calciatore(voce, "Ivan Provedel", "it", 1994)
    assert bio.e_calciatore(voce, "Ivan Provedel", "it")  # anno non noto
    assert not bio.e_calciatore(voce, "Ivan Provedel", "it", 1987)  # un omonimo
    assert not bio.e_calciatore(
        riassunto("Marco Rossi", "pagina di disambiguazione", "", tipo="disambiguation"),
        "Marco Rossi", "it",
    )
    assert not bio.e_calciatore(
        riassunto("Marco Rossi", "politico italiano", "Marco Rossi è un politico."), "Marco Rossi", "it"
    )
    en = riassunto("Josep Martínez", "Spanish footballer (born 1998)", "Josep Martínez is a Spanish footballer.", lingua="en")
    assert bio.e_calciatore(en, "Josep Martínez", "en", 1998)
    assert not bio.e_calciatore(en, "Josep Martínez", "it", 1998)  # radici italiane


def test_taglia_estratto():
    assert bio.taglia_estratto("Breve.  Testo") == "Breve. Testo"
    lungo = "Prima frase abbastanza lunga da contare. " * 30
    tagliato = bio.taglia_estratto(lungo, 200)
    assert len(tagliato) <= 200 and tagliato.endswith(".")
    parole = "parola " * 100
    assert bio.taglia_estratto(parole, 50).endswith("…")


# ---------------------------------------------------------------- Wikipedia: ricerca

@respx.mock
def test_profilo_wikipedia_italiano(client):
    cerca = respx.get(WIKI_IT).mock(return_value=httpx.Response(
        200, json=ricerca("Ivan Provedel", "Christos Mandas", "Serie A 2026-2027")
    ))
    respx.get("https://it.wikipedia.org/api/rest_v1/page/summary/Ivan_Provedel").mock(
        return_value=httpx.Response(200, json=riassunto(
            "Ivan Provedel", "calciatore italiano (1994-)",
            "Ivan Provedel è un calciatore italiano, portiere dell'Inter.",
        ))
    )
    p = client.profilo_wikipedia("Ivan Provedel", 1994)
    assert p == bio.ProfiloWiki(
        titolo="Ivan Provedel", url="https://it.wikipedia.org/wiki/Ivan_Provedel",
        estratto="Ivan Provedel è un calciatore italiano, portiere dell'Inter.", lingua="it",
    )
    assert cerca.calls[0].request.url.params["srsearch"] == "Ivan Provedel calciatore"
    assert "Cartellino" in cerca.calls[0].request.headers["User-Agent"]


@respx.mock
def test_profilo_ripiega_sull_inglese(client):
    respx.get(WIKI_IT).mock(return_value=httpx.Response(200, json=ricerca("Serie A 2026-2027")))
    respx.get(WIKI_EN).mock(return_value=httpx.Response(200, json=ricerca("Josep Martínez")))
    respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Josep_Mart%C3%ADnez").mock(
        return_value=httpx.Response(200, json=riassunto(
            "Josep Martínez", "Spanish footballer (born 1998)",
            "Josep Martínez is a Spanish professional footballer.", lingua="en",
        ))
    )
    p = client.profilo_wikipedia("Josep Martínez", 1998)
    assert p.lingua == "en" and p.url.startswith("https://en.wikipedia.org/")


@respx.mock
def test_profilo_dubbio_non_restituisce_nulla(client):
    respx.get(WIKI_IT).mock(return_value=httpx.Response(200, json=ricerca("Marco Rossi")))
    respx.get(WIKI_EN).mock(return_value=httpx.Response(200, json=ricerca("Marco Rossi")))
    respx.get("https://it.wikipedia.org/api/rest_v1/page/summary/Marco_Rossi").mock(
        return_value=httpx.Response(200, json=riassunto("Marco Rossi", "pagina di disambiguazione", "", tipo="disambiguation"))
    )
    respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Marco_Rossi").mock(
        return_value=httpx.Response(200, json=riassunto("Marco Rossi", "Italian footballer (born 1987)", "Marco Rossi is a footballer.", lingua="en"))
    )
    # l'unico calciatore trovato è nato in un altro anno: un omonimo
    assert client.profilo_wikipedia("Marco Rossi", 2001) is None


@respx.mock
def test_profilo_senza_risultati_e_errore(client):
    respx.get(WIKI_IT).mock(return_value=httpx.Response(200, json={"query": {"search": []}}))
    respx.get(WIKI_EN).mock(return_value=httpx.Response(500))
    with pytest.raises(ErroreFonte):
        client.profilo_wikipedia("Nessuno Noto")
