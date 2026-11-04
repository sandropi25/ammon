"""Verifica quali stagioni sono accessibili con la chiave API-Football in uso.

Consuma 3 richieste del piano giornaliero.
"""
import os
import sys

import httpx

URL_API = "https://v3.football.api-sports.io"


def stampa_stagioni(client: httpx.Client, id_lega: int) -> None:
    risposta = client.get("/leagues", params={"id": id_lega}).json()
    print(f"Lega {id_lega} - errori: {risposta.get('errors')}")
    for voce in risposta.get("response", []):
        print(f"  {voce['league']['name']}")
        for stagione in voce.get("seasons", []):
            copertura = stagione.get("coverage", {}).get("fixtures", {})
            print(
                f"    {stagione['year']}: "
                f"statistiche giocatori={copertura.get('statistics_players')}, "
                f"formazioni={copertura.get('lineups')}"
            )


def main() -> int:
    chiave = os.environ.get("API_FOOTBALL_KEY")
    if not chiave:
        print("Errore: la variabile d'ambiente API_FOOTBALL_KEY non e' impostata.")
        print("Impostala con la tua chiave API-Football e riesegui lo script.")
        return 2
    with httpx.Client(
        base_url=URL_API, headers={"x-apisports-key": chiave}, timeout=30
    ) as client:
        stampa_stagioni(client, 135)
        stampa_stagioni(client, 2)
        prova = client.get(
            "/fixtures", params={"league": 135, "season": 2026, "next": 1}
        ).json()
        print(f"Prova stagione 2026 - errori: {prova.get('errors')}")
        print(f"Prova stagione 2026 - risultati: {prova.get('results')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
