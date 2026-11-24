# Marcatori beta — piano

> Esecuzione: nativa (l'utente ha detto "vai col modello").

**Goal:** probabilità "segna almeno un gol" per ogni giocatore delle partite dei 4 campionati,
verificata 2024→2025, mostrata nell'app beta `app_marcatori/Marcatori.py`.
**Architettura:** caricamento in blocco delle presenze (una query), storico incrementale in ordine
di data (somme con decadimento), previsione pura; calibrazione Platt. Nessuna query per partita.
**Spec:** `docs/superpowers/specs/2026-11-24-marcatori-beta-design.md`

## Vincoli
- Ogni previsione usa solo partite precedenti al calcio d'inizio.
- Coefficienti in Impostazione `marcatori_coefficienti`; l'app beta legge solo.
- L'app dei cartellini non cambia.

## Review focus
- Giocatore senza storico (nuovo acquisto): prior del ruolo, mai probabilità 0 o errore.
- Ruolo mancante (molte presenze hanno ruolo None): ruolo dell'anagrafica o il più frequente.
- Portieri: probabilità quasi nulla.
- Partita con formazioni solo probabili (niente panchina): solo titolari.
- Squadra neopromossa senza storico: forza = media del campionato.

### Task 1: modello (`src/ammonizioni/marcatori/modello.py`)
- `Parametri(emivita_giorni, prior_squadra, prior_minuti, peso_tiri, a, b)`.
- `Storico.aggiorna(partita: PartitaM, presenze: list[PresenzaM])`, `Storico.prevedi(partita, rosa: list[Giocante]) -> list[Previsione]`.
- Test: `tests/marcatori/test_modello.py` (prior per nuovi, portiere basso, casa > trasferta a
  parità, attaccante prolifico in cima, nessun dato futuro).

### Task 2: dati e verifica (`marcatori/dati.py`, `marcatori/verifica.py`, `scripts/calibra_marcatori.py`)
- `carica(s, campionati, dal) -> (partite, presenze per partita)`; `percorri(...)` genera
  previsioni fuori campione; `stima_platt`; griglia su 2024, misura su 2025; `--salva`.

### Task 3: app beta
- Partite dei prossimi 7 giorni per campionato, classifica marcatori con %; formazione
  ufficiale + panchina se c'è, altrimenti probabile.

### Task 4: automatismi
- Cernita marcatori salvata dal pre-partita; resoconto marcatori a fine giornata (modulo resoconto).
